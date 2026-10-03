package com.kplasma.analysisagent.decision;
import com.kplasma.analysisagent.workspace.WorkspaceTestSupport;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;
class DecisionValidationTest extends WorkspaceTestSupport {
    @Test void savesDistinctRevAndExpSnapshotsWithoutGraphsAndExactRetryStoresOneRecord() throws Exception {
        var rev=write(review());assertThat(ok("POST","/api/decisions",rev,"rev").has("version")).isFalse();
        var exp=write(experiment());var saved=ok("POST","/api/decisions",exp,"exp");assertThat(saved.get("version").intValue()).isEqualTo(2);assertThat(saved.get("candidates").get(0).get("runVersionId")).isEqualTo(refs.get(0).get("runVersionId"));
        assertThat(ok("POST","/api/decisions",exp,"exp")).isEqualTo(saved);assertThat(ok("GET","/api/decisions",null,null).size()).isEqualTo(2);
        var changed=experiment();changed.put("overallComment","different");rejects("POST","/api/decisions",write(changed),"exp",409,"IDEMPOTENCY_CONFLICT");
        rejects("POST","/api/decisions",exp,null,400,"INVALID_DECISION");
    }
    @Test void ordinaryExpRequiresOneAdoptionTwoExtrasAndCommonCommentWithoutDemoException() throws Exception {
        for(String value:List.of("HOLD","REJECT","ALTERNATIVE","COMPARISON")) {var exp=experiment();((ObjectNode)exp.get("candidates").get(0)).put("decision",value);rejects("POST","/api/decisions",write(exp),UUID.randomUUID().toString(),400,"INVALID_DECISION");}
        var missing=experiment();missing.put("overallComment"," ");rejects("POST","/api/decisions",write(missing),"memo",400,"INVALID_DECISION");
        var two=experiment();var extra=snapshot(1,true);extra.put("decision","ADOPT");two.set("candidates",mapper.valueToTree(List.of(snapshot(0,true),extra)));rejects("POST","/api/decisions",write(two),"two",400,"INVALID_DECISION");
        var tooMany=experiment();tooMany.set("candidates",mapper.valueToTree(List.of(snapshot(0,true),snapshot(1,true),snapshot(2,true),snapshot(3,true))));rejects("POST","/api/decisions",write(tooMany),"four",400,"INVALID_DECISION");
        var valid=experiment();valid.set("comparedRunIds",mapper.valueToTree(List.of("SYNTHETIC-1","SYNTHETIC-2")));valid.set("comparedRunRefs",mapper.valueToTree(refs.subList(1,3)));var rejected=snapshot(2,true);rejected.put("decision","REJECT");valid.set("candidates",mapper.valueToTree(List.of(snapshot(0,true),snapshot(1,true),rejected)));assertThat(ok("POST","/api/decisions",write(valid),"three").get("candidates").size()).isEqualTo(3);
    }
    @Test void revRequiresCommentUniqueRunsKnownVersionsAndExplanationBaseline() throws Exception {
        var missing=review();missing.put("comment","");rejects("POST","/api/decisions",write(missing),"memo",400,"INVALID_DECISION");
        var duplicate=review();duplicate.set("comparedRunIds",mapper.valueToTree(List.of("SYNTHETIC-0")));duplicate.set("comparedRunRefs",mapper.valueToTree(List.of(refs.get(0))));rejects("POST","/api/decisions",write(duplicate),"dup",400,"INVALID_DECISION");
        var nonexistent=review();((ObjectNode)nonexistent.get("targetRunRef")).put("runVersionId",UUID.randomUUID().toString());rejects("POST","/api/decisions",write(nonexistent),"unknown",400,"INVALID_DECISION");
        var mismatched=review();mismatched.put("targetRunId","SYNTHETIC-1");rejects("POST","/api/decisions",write(mismatched),"wrong",400,"INVALID_DECISION");
        var explanation=review();explanation.put("analysisType","EXPLANATION");rejects("POST","/api/decisions",write(explanation),"no-baseline",400,"INVALID_DECISION");
        explanation.set("comparedRunIds",mapper.valueToTree(List.of("SYNTHETIC-1")));explanation.set("comparedRunRefs",mapper.valueToTree(List.of(refs.get(1))));explanation.set("runSnapshots",mapper.valueToTree(List.of(snapshot(0,false),snapshot(1,false))));assertThat(ok("POST","/api/decisions",write(explanation),"baseline").get("comparedRunRefs").size()).isEqualTo(1);
    }
    @Test void inconsistentSnapshotRefsOrWriteInventoryAndGraphMetadataAreRejected() throws Exception {
        var rev=review();((ObjectNode)rev.get("runSnapshots").get(0)).put("runVersionId",refs.get(1).get("runVersionId").stringValue());rejects("POST","/api/decisions",write(rev),"snapshot",400,"INVALID_DECISION");
        var body=new HashMap<>(write(review()));body.put("runRefs",List.of(refs.get(1)));rejects("POST","/api/decisions",body,"inventory",400,"INVALID_DECISION");
        rev=review();rev.set("goals",mapper.valueToTree(List.of(Map.of("analysis",Map.of("residualTrace",List.of(List.of(1,2)))))));rejects("POST","/api/decisions",write(rev),"graph",400,"INVALID_DECISION");
        assertThat(ok("GET","/api/decisions",null,null).isEmpty()).isTrue();
    }
}
