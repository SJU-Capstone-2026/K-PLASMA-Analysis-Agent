package com.kplasma.analysisagent.workspace;

import java.nio.file.Files;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class WorkspacePersistenceTest extends WorkspaceTestSupport {
    @Test void requeryPreservesFrozenAnswersAndImmutableRoleRefsWhilePatchChangesOnlyOneTurnUi() throws Exception {
        var first=turn();var second=turn();
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",first),"a");
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",second),"b");
        var before=state();var after=ok("PATCH","/api/workspace/turns/"+first.get("id").stringValue()+"/ui",Map.of("stateToken",token(),"ui",Map.of("selectedCandidateRunId","SYNTHETIC-1","runDetailTabs",Map.of("SYNTHETIC-1","ion-energy"),"collapsed",true)),null);
        assertThat(after.get("stateToken").get("revision").longValue()).isEqualTo(before.get("stateToken").get("revision").longValue()+1);
        var reloaded=state().get("conversation").get("turns");assertThat(reloaded.size()).isEqualTo(2);
        assertThat(reloaded.get(0).get("answerSnapshot")).isEqualTo(before.get("conversation").get("turns").get(0).get("answerSnapshot"));
        assertThat(reloaded.get(0).get("answerRunRefs")).isEqualTo(first.get("answerRunRefs"));
        assertThat(reloaded.get(0).get("ui").get("collapsed").booleanValue()).isTrue();
        assertThat(reloaded.get(0).get("ui").get("runDetailTabs").get("SYNTHETIC-1").stringValue()).isEqualTo("ion-energy");
        assertThat(reloaded.get(1)).isEqualTo(before.get("conversation").get("turns").get(1));
    }
    @Test void referenceWritesActiveRunAndCandidateReferenceIndependentlyAndContinueAddsNoTurn() throws Exception {
        Map<String,Object> body=new HashMap<>();body.put("stateToken",token());body.put("activeRun",refs.get(0));body.put("candidateReference",Map.of("kind","단일 Run","runs",List.of(refs.get(1))));
        ok("PUT","/api/workspace/reference",body,null);var reloaded=state();assertThat(reloaded.get("conversation").get("activeRun")).isEqualTo(refs.get(0));assertThat(reloaded.get("candidateReference").get("runs").get(0)).isEqualTo(refs.get(1));
        body.put("stateToken",token());body.put("activeRun",refs.get(2));body.put("candidateReference",null);ok("PUT","/api/workspace/reference",body,null);
        assertThat(state().get("conversation").get("activeRun")).isEqualTo(refs.get(2));assertThat(state().get("candidateReference").isNull()).isTrue();assertThat(state().get("conversation").get("turns").isEmpty()).isTrue();
        body.remove("activeRun");body.put("stateToken",token());rejects("PUT","/api/workspace/reference",body,null,400,"INVALID_WORKSPACE");
    }
    @Test void exactReplayBypassesOriginalRevisionButReturnsCurrentTokenAndChangedPayloadConflicts() throws Exception {
        var original=Map.of("stateToken",token(),"turn",turn());ok("POST","/api/workspace/turns",original,"retry");
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",turn()),"next");
        var authoritative=state();assertThat(ok("POST","/api/workspace/turns",original,"retry")).isEqualTo(authoritative);assertThat(state().get("conversation").get("turns").size()).isEqualTo(2);
        rejects("POST","/api/workspace/turns",original,"fresh",409,"STALE_CONTEXT");
        var changed=(ObjectNode)((ObjectNode)original.get("turn")).deepCopy();changed.put("question","changed");rejects("POST","/api/workspace/turns",Map.of("stateToken",original.get("stateToken"),"turn",changed),"retry",409,"IDEMPOTENCY_CONFLICT");
    }
    @Test void newConversationKeepsDecisionsButRejectsOldKeysAndResetKeepsRunsAndOriginals() throws Exception {
        var append=Map.of("stateToken",token(),"turn",turn());ok("POST","/api/workspace/turns",append,"old");var decision=write(review());ok("POST","/api/decisions",decision,"decision");
        var before=token();var fresh=ok("POST","/api/workspace/new-conversation",Map.of("stateToken",before),null);
        assertThat(fresh.get("stateToken").get("workspaceEpoch")).isEqualTo(before.get("workspaceEpoch"));assertThat(fresh.get("stateToken").get("conversationEpoch").longValue()).isEqualTo(before.get("conversationEpoch").longValue()+1);
        assertThat(fresh.get("conversation").get("turns").isEmpty()).isTrue();assertThat(ok("GET","/api/decisions",null,null).size()).isEqualTo(1);
        rejects("POST","/api/workspace/turns",append,"old",409,"STALE_CONTEXT");assertThat(ok("POST","/api/decisions",decision,"decision").get("reviewId").stringValue()).isEqualTo("REV-artificial");
        long versions=jdbc.queryForObject("select count(*) from run_version",Long.class), originals=jdbc.queryForObject("select count(*) from source_file",Long.class);
        var old=token();var reset=ok("POST","/api/workspace/reset",Map.of("stateToken",old),null);assertThat(reset.get("stateToken").get("workspaceEpoch").longValue()).isEqualTo(old.get("workspaceEpoch").longValue()+1);
        assertThat(ok("GET","/api/decisions",null,null).isEmpty()).isTrue();assertThat(reset.get("conversation").get("activeRun").isNull()).isTrue();assertThat(reset.get("candidateReference").isNull()).isTrue();
        assertThat(jdbc.queryForObject("select count(*) from run_version",Long.class)).isEqualTo(versions);assertThat(jdbc.queryForObject("select count(*) from source_file",Long.class)).isEqualTo(originals);assertThat(Files.readString(ROOT.resolve("original.txt"))).isEqualTo("artificial original");
        rejects("POST","/api/decisions",decision,"decision",409,"STALE_CONTEXT");rejects("POST","/api/workspace/turns",append,"old",409,"STALE_CONTEXT");
    }
    @Test void invalidUiFieldsTypesGraphCopiesAndMismatchedRoleInventoryFailWithoutMutation() throws Exception {
        var t=turn();ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",t),"valid");String path="/api/workspace/turns/"+t.get("id").stringValue()+"/ui";
        for(var patch:List.of(Map.of("question","changed"),Map.of("collapsed","yes"),Map.of("openRunIds",List.of(2)),Map.of("runDetailTabs",Map.of("x",2)))) rejects("PATCH",path,Map.of("stateToken",token(),"ui",patch),null,400,"INVALID_WORKSPACE");
        var stale=token();ok("PATCH",path,Map.of("stateToken",token(),"ui",Map.of("collapsed",true)),null);rejects("PATCH",path,Map.of("stateToken",stale,"ui",Map.of("collapsed",false)),null,409,"STALE_CONTEXT");
        var invalid=turn();((ObjectNode)invalid.get("answerSnapshot")).set("iedDistribution",mapper.valueToTree(List.of(Map.of("energy",1,"intensity",2))));rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",invalid),"graph",400,"INVALID_WORKSPACE");
        invalid=turn();((ObjectNode)invalid.get("answerSnapshot")).set("candidateRunRefs",mapper.valueToTree(List.of(refs.get(2))));rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",invalid),"role",400,"INVALID_WORKSPACE");
        invalid=turn();((ObjectNode)invalid.get("context")).put("runId","WRONG-ID");rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",invalid),"id",400,"INVALID_WORKSPACE");
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
    }
    @Test void roleRefMetadataRejectsMalformedOrDuplicateIdentitiesButSupportsOldBaselineAndNewCandidateSameId() throws Exception {
        var bad=turn();((ObjectNode)bad.get("answerSnapshot")).set("candidateRunRefs",mapper.valueToTree(List.of("SYNTHETIC-1")));
        rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",bad),"bad-role",400,"INVALID_WORKSPACE");
        bad=turn();((ObjectNode)bad.get("answerSnapshot")).set("candidateRunRefs",mapper.valueToTree(List.of(refs.get(1),refs.get(1))));
        rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",bad),"duplicate-role",400,"INVALID_WORKSPACE");
        UUID newer=UUID.randomUUID();jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),summary,jsonb_set(full_run,'{runVersionId}',to_jsonb(?::text)) from run_version where id=?",newer,newer.toString(),UUID.fromString(refs.get(0).get("runVersionId").stringValue()));
        var candidate=mapper.valueToTree(Map.of("runId","SYNTHETIC-0","runVersionId",newer.toString()));var good=turn();good.set("answerRunRefs",mapper.valueToTree(List.of(refs.get(0),candidate)));
        ((ObjectNode)good.get("answerSnapshot")).set("candidateRunRefs",mapper.valueToTree(List.of(candidate)));
        var saved=ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",good),"versions").get("conversation").get("turns").get(0);
        assertThat(saved.get("context")).isEqualTo(refs.get(0));assertThat(saved.get("answerSnapshot").get("candidateRunRefs").get(0)).isEqualTo(candidate);
        assertThat(saved.get("answerSnapshot").get("memoryRequest").get("referenceRunRefs").get(0)).isEqualTo(refs.get(0));
    }
    @Test void simultaneousExactRetriesStoreOneTurnUnderTheDatabaseLock() throws Exception {
        var body=Map.of("stateToken",token(),"turn",turn());
        try(var executor=java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            var first=executor.submit(()->send("POST","/api/workspace/turns",body,"parallel"));var second=executor.submit(()->send("POST","/api/workspace/turns",body,"parallel"));
            assertThat(first.get().statusCode()).isEqualTo(200);assertThat(second.get().statusCode()).isEqualTo(200);
        }
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
    }
    @Test void nullableUiValuesAndDetailTabMergingPersistAndReferenceChangesRejectStaleTokens() throws Exception {
        var t=turn();ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",t),"turn");String path="/api/workspace/turns/"+t.get("id").stringValue()+"/ui";
        ok("PATCH",path,Map.of("stateToken",token(),"ui",Map.of("runDetailTabs",Map.of("SYNTHETIC-0","ied"),"continuedRunId","SYNTHETIC-0")),null);
        Map<String,Object> patch=new HashMap<>();patch.put("continuedRunId",null);patch.put("selectedCandidateRunId",null);patch.put("runDetailTabs",Map.of("SYNTHETIC-1","potential"));
        var saved=ok("PATCH",path,Map.of("stateToken",token(),"ui",patch),null).get("conversation").get("turns").get(0).get("ui");assertThat(saved.get("continuedRunId").isNull()).isTrue();assertThat(saved.get("runDetailTabs").size()).isEqualTo(2);
        Map<String,Object> reference=new HashMap<>();reference.put("stateToken",token());reference.put("candidateReference",null);reference.put("activeRun",refs.get(0));ok("PUT","/api/workspace/reference",reference,null);
        rejects("PUT","/api/workspace/reference",reference,null,409,"STALE_CONTEXT");reference.put("stateToken",token());var invalid=refs.get(0).deepCopy();((ObjectNode)invalid).putNull("runVersionId");reference.put("activeRun",invalid);rejects("PUT","/api/workspace/reference",reference,null,400,"INVALID_WORKSPACE");
    }

    @Test void graphSeriesCopiesAreRejectedWhileCandidateConditionAndMetricScalarsRemainAllowed() throws Exception {
        var bad=turn();((ObjectNode)bad.get("answerSnapshot")).set("graphs",mapper.valueToTree(List.of(Map.of("id","ied","series",List.of(List.of(1,2))))));
        rejects("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",bad),"series",400,"INVALID_WORKSPACE");
        var good=turn();((ObjectNode)good.get("answerSnapshot")).set("candidateGroups",mapper.valueToTree(Map.of("groups",List.of(Map.of("id","results","candidates",List.of(Map.of("runId","SYNTHETIC-1","conditions",List.of(Map.of("metric","pressure","value",2)),"metrics",List.of(Map.of("metric","meanIonEnergy","value",2)),"qualityLabel","검증됨")))))));
        assertThat(ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",good),"scalars").get("conversation").get("turns").get(0).get("answerSnapshot").get("candidateGroups")).isEqualTo(good.get("answerSnapshot").get("candidateGroups"));
    }

}
