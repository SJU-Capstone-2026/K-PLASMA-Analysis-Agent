package com.kplasma.analysisagent.workspace;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class RunDeletionReferencesTest extends WorkspaceTestSupport {
    // Chat snapshots remain readable evidence, but they must not make ordinary Run cleanup impossible.
    @Test void conversationReferenceDoesNotBlockDeletionOrRemoveTheTurn() throws Exception {
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",turn()),"turn");
        var before=state();
        var result=ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0","SYNTHETIC-3")),null);
        assertThat(result.get("deletedRunIds")).hasSize(2);
        var after=state();
        assertThat(after.get("conversation").get("turns")).isEqualTo(before.get("conversation").get("turns"));
        assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(2);
    }
    @Test void storedDecisionBlocksDeletionAcrossNewConversations() throws Exception {
        ok("POST","/api/decisions",write(review()),"decision");
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        var result=send("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(result.statusCode()).isEqualTo(409);assertThat(json(result).get("message").stringValue()).contains("판단","SYNTHETIC-0");
        assertThat(ok("GET","/api/decisions",null,null).size()).isEqualTo(1);
    }
    @Test void deletedCurrentReferencesAreReleasedWithoutBlockingOrClearingOtherReferences() throws Exception {
        var body=new HashMap<String,Object>();body.put("stateToken",token());body.put("activeRun",refs.get(0));body.put("candidateReference",Map.of("kind","후보 집합","runs",List.of(refs.get(1))));
        ok("PUT","/api/workspace/reference",body,null);
        long revision=state().get("stateToken").get("revision").longValue();
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        var activeDeleted=state();
        assertThat(activeDeleted.get("conversation").get("activeRun").isNull()).isTrue();
        assertThat(activeDeleted.get("candidateReference").get("runs").get(0).get("runId").stringValue()).isEqualTo("SYNTHETIC-1");
        assertThat(activeDeleted.get("stateToken").get("revision").longValue()).isEqualTo(revision+1);
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-1")),null);
        assertThat(state().get("candidateReference").isNull()).isTrue();
    }
}
