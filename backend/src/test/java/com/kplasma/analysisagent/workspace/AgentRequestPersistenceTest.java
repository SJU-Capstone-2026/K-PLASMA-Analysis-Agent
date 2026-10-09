package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.mockito.Mockito.*;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class AgentRequestPersistenceTest extends WorkspaceTestSupport {
    @MockitoSpyBean JdbcTemplate observedJdbc;
    @ParameterizedTest @ValueSource(ints={2,5,150})
    void comparisonMaterializationUsesTwoBulkReadsAtEverySelectionSize(int size)throws Exception{
        var template=jdbc.queryForObject("select summary::text from run_version where id=?::uuid",String.class,refs.getFirst().get("runVersionId").stringValue());
        var source=jdbc.queryForObject("select source_id from run_version where id=?::uuid",UUID.class,refs.getFirst().get("runVersionId").stringValue());
        for(int i=4;i<size;i++){
            String runId="SYNTHETIC-"+i;UUID version=UUID.randomUUID();var full=(tools.jackson.databind.node.ObjectNode)mapper.readTree(template);full.put("runId",runId);full.put("runVersionId",version.toString());
            jdbc.update("insert into run(run_id) values (?)",runId);jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) values (?,?,?,now(),?::jsonb,?::jsonb)",version,runId,source,full.toString(),full.toString());
            jdbc.update("update run set current_version_id=? where run_id=?",version,runId);refs.add(mapper.valueToTree(Map.of("runId",runId,"runVersionId",version.toString())));
        }
        var chosen=refs.subList(0,size);var saved=turn();saved.set("answerRunRefs",mapper.valueToTree(chosen));
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",saved),"bulk-turn");
        var origins=chosen.stream().map(ref->Map.of("ref",ref,"kind","run_tag","turnId",saved.get("id").stringValue())).toList();
        var job=ok("POST","/api/agent/requests",Map.of("text","선택한 실험 비교","stateToken",token(),"attachedRunRefs",chosen,"referenceOrigins",origins),"bulk-request");
        var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();internal(path+"/heartbeat",mutation(claimed,"operationKind","compare_runs"));
        var input=new HashMap<>(fence(claimed));input.put("referencesOnly",true);input.put("requiredRunRefs",chosen);
        clearInvocations(observedJdbc);var manifest=internal(path+"/context",input);
        var runReads=mockingDetails(observedJdbc).getInvocations().stream().filter(call->call.getArguments().length==3&&call.getArguments()[1] instanceof org.springframework.jdbc.core.RowMapper<?> &&call.getArguments()[0] instanceof String sql&&sql.startsWith("select")&&sql.contains("from run_version")).toList();
        assertThat(runReads).hasSize(2);assertThat(manifest.get("referencedRuns").size()).isEqualTo(size);assertThat(manifest.get("catalogRunRefs").size()).isZero();
        clearInvocations(observedJdbc);internal(path+"/context",input);
        assertThat(mockingDetails(observedJdbc).getInvocations().stream().filter(call->call.getArguments().length==3&&call.getArguments()[1] instanceof org.springframework.jdbc.core.RowMapper<?> &&call.getArguments()[0] instanceof String sql&&sql.startsWith("select")&&sql.contains("from run_version"))).hasSize(1);
    }
    @Test void runPickerFreezesAliasesAndResumePinsOnlySelectedVersions() throws Exception {
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","compare_runs"));
        internal(path+"/needs-input",mutation(claimed,"pendingInput",Map.of("type","run_selection","id","pick","message","비교할 실험을 선택해 주세요","minSelections",2,"baselineRequired",false,"optionsUrl","/api/agent"+path+"/run-options?pendingInputId=pick")));
        var options=ok("GET","/api/agent"+path+"/run-options?pendingInputId=pick",null,null);
        assertThat(options.get("options").size()).isEqualTo(4);
        var input=Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","runKeys",List.of("R1","R3")));
        var resumed=ok("POST","/api/agent"+path+"/resume",input,"pick-input");
        assertThat(resumed.get("status").stringValue()).isEqualTo("QUEUED");
        var next=claim();assertThat(next.get("context").get("comparisonReference").get("entries").size()).isEqualTo(2);
        var only=new HashMap<>(fence(next));only.put("referencesOnly",true);only.put("requiredRunRefs",List.of(options.get("options").get(0).get("ref"),options.get("options").get(2).get("ref")));
        var manifest=internal(path+"/context",only);
        assertThat(manifest.get("runs").size()).isZero();assertThat(manifest.get("referencedRuns").size()).isEqualTo(2);
        assertThat(manifest.get("catalogRunRefs").size()).isZero();
        assertThat(ok("POST","/api/agent"+path+"/resume",input,"pick-input").get("requestId")).isEqualTo(resumed.get("requestId"));
    }
    @Test void deletedOptionIsDisabledAndOnlySelectedDeletionCancelsComparison()throws Exception{
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","compare_runs"));
        internal(path+"/needs-input",mutation(claimed,"pendingInput",Map.of("type","run_selection","id","pick","message","실험 선택","minSelections",2,"baselineRequired",false)));
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-3")),null);
        var options=ok("GET","/api/agent"+path+"/run-options?pendingInputId=pick",null,null);
        assertThat(options.get("options").size()).isEqualTo(4);assertThat(options.get("options").get(3).get("selectable").booleanValue()).isFalse();
        var bad=send("POST","/api/agent"+path+"/resume",Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","runKeys",List.of("R1","R4"))),"deleted-option");assertThat(bad.statusCode()).isEqualTo(400);
        ok("POST","/api/agent"+path+"/resume",Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","runKeys",List.of("R1","R2"))),"valid-option");
        var next=claim();ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-2")),null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("RUNNING");
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(internalResponse(path+"/checkpoint",mutation(next,"payload",Map.of("late",true))).statusCode()).isEqualTo(409);
    }
    @Test void generalAnswerHasNoManifestAndSurvivesRunDeletion()throws Exception{
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","generate_answer"));
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("RUNNING");
        var fixture=mapper.readTree(java.nio.file.Files.readString(java.nio.file.Path.of("../agent/tests/support/answer-v2-wire.json")));
        var snapshot=(tools.jackson.databind.node.ObjectNode)fixture.get("general").deepCopy();snapshot.put("originalQuestion","설명해줘");
        var answer=new HashMap<String,Object>();answer.put("intent","GENERAL_ANSWER");answer.put("status","ANSWER_READY");answer.put("candidates",List.of());answer.put("explanation",null);answer.put("usedRunRefs",List.of());answer.put("answerSnapshot",snapshot);
        assertThat(internal(path+"/finalize",mutation(claimed,"answer",answer)).get("status").stringValue()).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("select manifest is null from agent_request where id=?",Boolean.class,UUID.fromString(job.get("requestId").stringValue()))).isTrue();
    }
    private HttpResponse<String> internalResponse(String path,Object body) throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+path))
            .header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        return HttpClient.newHttpClient().send(request,HttpResponse.BodyHandlers.ofString());
    }
    private JsonNode internal(String path,Object body) throws Exception {
        var response=internalResponse(path,body);
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);
    }
    private JsonNode accepted() throws Exception {return ok("POST","/api/agent/requests",Map.of("text","설명해줘","stateToken",token()),UUID.randomUUID().toString());}
    private Map<String,Object> fence(JsonNode claim){return Map.of("claimGeneration",claim.get("claimGeneration").longValue(),"requestRevision",claim.get("requestRevision").longValue());}
    private Map<String,Object> mutation(JsonNode claim,String key,Object value){var body=new HashMap<>(fence(claim));body.put(key,value);return body;}
    private JsonNode claim() throws Exception {return internal("/claim",Map.of("workerId","test-worker","leaseSeconds",60));}
    @Test void acceptedRequestIsDurableAndExactRetryCreatesOnlyOneJob() throws Exception {
        var body=Map.of("text","이온 플럭스를 설명해줘","stateToken",token());
        var accepted=ok("POST","/api/agent/requests",body,"request-a");
        assertThat(accepted.get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(ok("POST","/api/agent/requests",body,"request-a").get("requestId")).isEqualTo(accepted.get("requestId"));
        assertThat(state().get("activeAgentRequest").get("requestId")).isEqualTo(accepted.get("requestId"));
        var claim=internal("/claim",Map.of("workerId","test-worker","leaseSeconds",60));
        assertThat(claim.get("request").get("requestId")).isEqualTo(accepted.get("requestId"));
        assertThat(claim.get("claimGeneration").longValue()).isEqualTo(1);
    }
    @Test void expiredClaimCannotOverwriteCheckpointAndInputResumePreservesSavedState() throws Exception {
        var job=accepted();String path="/requests/"+job.get("requestId").stringValue();var old=claim();
        internal(path+"/checkpoint",mutation(old,"payload",Map.of("checkpoint","saved-before-crash")));
        jdbc.update("update agent_request set lease_until=now()-interval '1 second' where id=?",UUID.fromString(job.get("requestId").stringValue()));
        var fresh=claim();assertThat(fresh.get("claimGeneration").longValue()).isGreaterThan(old.get("claimGeneration").longValue());
        var rejected=internalResponse(path+"/checkpoint",mutation(old,"payload",Map.of("checkpoint","stale")));assertThat(rejected.statusCode()).isEqualTo(409);assertThat(json(rejected).get("code").stringValue()).isEqualTo("STALE_CLAIM");
        internal(path+"/needs-input",mutation(fresh,"pendingInput",Map.of("id","pressure-input","message","압력을 알려주세요")));
        var input=Map.of("expectedRequestRevision",0,"pendingInputId","pressure-input","input",Map.of("text","10 mTorr"));
        var resumed=ok("POST","/api/agent/requests/"+job.get("requestId").stringValue()+"/resume",input,"reply");
        assertThat(resumed.get("requestRevision").longValue()).isEqualTo(1);assertThat(resumed.get("inputEvents").size()).isEqualTo(1);
        assertThat(ok("POST","/api/agent/requests/"+job.get("requestId").stringValue()+"/resume",input,"reply")).isEqualTo(resumed);
        assertThat(jdbc.queryForObject("select payload->>'checkpoint' from agent_checkpoint where request_id=?",String.class,UUID.fromString(job.get("requestId").stringValue()))).isEqualTo("saved-before-crash");
    }
    @Test void conceptFinalizationIsAtomicReplayableAndDoesNotRequireAnyRun() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/checkpoint",mutation(claim,"payload",Map.of("draft","private-state")));
        var answer=Map.of("intent","CONCEPT_EXPLANATION","status","SUCCESS","candidates",List.of(),"usedRunRefs",List.of(),"answerSnapshot",Map.of("implementationId","v1","kind","explain_concept","summary","개념 설명"));
        var completed=internal(path+"/finalize",mutation(claim,"answer",answer));assertThat(completed.get("status").stringValue()).isEqualTo("COMPLETED");
        assertThat(internal(path+"/finalize",mutation(claim,"answer",answer))).isEqualTo(completed);
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from agent_checkpoint where request_id=?",Long.class,UUID.fromString(job.get("requestId").stringValue()))).isZero();
        var changed=new HashMap<>(answer);changed.put("status","CHANGED");assertThat(internalResponse(path+"/finalize",mutation(claim,"answer",changed)).statusCode()).isEqualTo(409);
    }
    @Test void resetFencesLateWriterAndErasesAllTransientUserContent() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/checkpoint",mutation(claim,"payload",Map.of("draft","private-state")));
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        assertThat(internalResponse(path+"/checkpoint",mutation(claim,"payload",Map.of("draft","late"))).statusCode()).isEqualTo(409);
        var cleared=ok("GET","/api/agent"+path,null,null);assertThat(cleared.get("question").isNull()).isTrue();assertThat(cleared.get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(cleared.get("error").isNull()).isTrue();
        assertThat(state().get("activeAgentRequest").isNull()).isTrue();assertThat(jdbc.queryForObject("select count(*) from agent_checkpoint",Long.class)).isZero();
    }
    @Test void modelAttemptBudgetPersistsAcrossClaimLossAndRepairsShareSameBudget() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        for(int i=0;i<4;i++)internal(path+"/attempt",mutation(claim,"stage",i%2==0?"interpret":"interpret_repair"));
        assertThat(internalResponse(path+"/attempt",mutation(claim,"stage","interpret")).statusCode()).isEqualTo(409);
        internal(path+"/attempt",mutation(claim,"stage","explain"));
        jdbc.update("update agent_request set lease_until=now()-interval '1 second' where id=?",UUID.fromString(job.get("requestId").stringValue()));
        var next=claim();assertThat(internalResponse(path+"/attempt",mutation(next,"stage","interpret")).statusCode()).isEqualTo(409);
    }
    @Test void threeExpiredClaimsEndWithVisibleFailureAndFenceTheLastWorker() throws Exception {
        var job=accepted();UUID id=UUID.fromString(job.get("requestId").stringValue());String path="/requests/"+id;JsonNode last=null;
        for(int attempt=1;attempt<=3;attempt++){
            last=claim();assertThat(last.get("request").get("requestId")).isEqualTo(job.get("requestId"));
            internal(path+"/checkpoint",mutation(last,"payload",Map.of("checkpoint","recoverable")));
            jdbc.update("update agent_request set lease_until=now()-interval '1 second' where id=?",id);
        }
        assertThat(claim().get("request").isNull()).isTrue();
        var failed=ok("GET","/api/agent"+path,null,null);assertThat(failed.get("status").stringValue()).isEqualTo("FAILED");
        assertThat(failed.get("error").get("code").stringValue()).isEqualTo("CLAIM_ATTEMPT_LIMIT");
        assertThat(state().get("activeAgentRequest").isNull()).isTrue();
        assertThat(state().get("failedAgentRequest").get("requestId")).isEqualTo(job.get("requestId"));
        assertThat(jdbc.queryForObject("select count(*) from agent_checkpoint where request_id=?",Long.class,id)).isZero();
        assertThat(internalResponse(path+"/checkpoint",mutation(last,"payload",Map.of("checkpoint","late"))).statusCode()).isEqualTo(409);
        assertThat(accepted().get("status").stringValue()).isEqualTo("QUEUED");
    }
    @Test void conceptContinuesAcrossUnrelatedReferenceChangesButDependentJobIsCancelled() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        var heartbeat=new HashMap<>(fence(claim));heartbeat.put("operationKind","explain_concept");heartbeat.put("dependsOnContext",false);internal(path+"/heartbeat",heartbeat);
        Map<String,Object> reference=new HashMap<>();reference.put("stateToken",token());reference.put("candidateReference",null);reference.put("activeRun",refs.getFirst());ok("PUT","/api/workspace/reference",reference,null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("RUNNING");
        ok("POST","/api/agent"+path+"/cancel",Map.of(),null);job=accepted();var dependent=claim();path="/requests/"+job.get("requestId").stringValue();
        var depends=new HashMap<>(fence(dependent));depends.put("operationKind","compare_runs");depends.put("dependsOnContext",true);internal(path+"/heartbeat",depends);
        reference.put("stateToken",token());reference.put("activeRun",refs.get(1));ok("PUT","/api/workspace/reference",reference,null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("CANCELLED");
    }
    @Test void unclassifiedConceptSurvivesRunDeletionButDependentClassificationIsFenced() throws Exception {
        Map<String,Object> reference=new HashMap<>();reference.put("stateToken",token());reference.put("candidateReference",null);reference.put("activeRun",refs.getFirst());ok("PUT","/api/workspace/reference",reference,null);
        var concept=accepted();String conceptPath="/requests/"+concept.get("requestId").stringValue();
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(ok("GET","/api/agent"+conceptPath,null,null).get("status").stringValue()).isEqualTo("QUEUED");
        var conceptClaim=claim();var kind=new HashMap<>(fence(conceptClaim));kind.put("operationKind","explain_concept");kind.put("dependsOnContext",false);
        assertThat(internal(conceptPath+"/heartbeat",kind).get("status").stringValue()).isEqualTo("RUNNING");
        ok("POST","/api/agent"+conceptPath+"/cancel",Map.of(),null);
        reference.put("stateToken",token());reference.put("activeRun",refs.get(1));ok("PUT","/api/workspace/reference",reference,null);
        var dependent=accepted();String dependentPath="/requests/"+dependent.get("requestId").stringValue();var old=claim();
        internal(dependentPath+"/checkpoint",mutation(old,"payload",Map.of("saved","before-classification")));
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-1")),null);
        var classified=new HashMap<>(fence(old));classified.put("operationKind","compare_runs");classified.put("dependsOnContext",true);
        assertThat(internal(dependentPath+"/heartbeat",classified).get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(internalResponse(dependentPath+"/checkpoint",mutation(old,"payload",Map.of("late",true))).statusCode()).isEqualTo(409);
    }
    @Test void unclassifiedReferenceChangeDefersCancellationUntilDependenciesAreKnown() throws Exception {
        var job=accepted();String path="/requests/"+job.get("requestId").stringValue();var before=claim();
        Map<String,Object> reference=new HashMap<>();reference.put("stateToken",token());reference.put("candidateReference",null);reference.put("activeRun",refs.getFirst());ok("PUT","/api/workspace/reference",reference,null);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("RUNNING");
        var classified=new HashMap<>(fence(before));classified.put("operationKind","compare_runs");classified.put("dependsOnContext",true);
        assertThat(internal(path+"/heartbeat",classified).get("status").stringValue()).isEqualTo("CANCELLED");
    }
    @Test void manifestPinsCatalogAndAcceptsAdditionalExactHistoricalVersionsWithoutRefreshingLatest() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        var first=internal(path+"/context",mutation(claim,"requiredRunRefs",List.of(refs.getFirst())));assertThat(first.get("runs").size()).isEqualTo(4);
        assertThat(first.get("runs").get(0).has("sourceFiles")).isFalse();assertThat(first.get("runs").get(0).has("iedDistribution")).isFalse();
        UUID newer=UUID.randomUUID();String old=refs.getFirst().get("runVersionId").stringValue();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),jsonb_set(summary,'{runVersionId}',to_jsonb(?::text)),jsonb_set(full_run,'{runVersionId}',to_jsonb(?::text)) from run_version where id=?",newer,newer.toString(),newer.toString(),UUID.fromString(old));
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'",newer);
        var second=internal(path+"/context",mutation(claim,"requiredRunRefs",List.of(Map.of("runId","SYNTHETIC-0","runVersionId",newer.toString()))));
        assertThat(second.get("runs")).isEqualTo(first.get("runs"));assertThat(second.get("referencedRuns").size()).isEqualTo(2);
    }
    @Test void v1AcceptsQuestionAfterPreservedLegacyTurnWithoutKind() throws Exception {
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",turn()),"legacy-turn");
        assertThat(accepted().get("status").stringValue()).isEqualTo("QUEUED");
    }
    @Test void workerTokenIsRequiredAndUiOnlyRevisionChangesDoNotInvalidateFinalizer() throws Exception {
        assertThat(send("POST","/internal/agent/claim",Map.of("workerId","unauthorized","leaseSeconds",60),null).statusCode()).isEqualTo(401);
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        var t=turn();ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",t),"unrelated-turn");
        ok("PATCH","/api/workspace/turns/"+t.get("id").stringValue()+"/ui",Map.of("stateToken",token(),"ui",Map.of("collapsed",true)),null);
        var answer=Map.of("intent","CONCEPT_EXPLANATION","status","SUCCESS","candidates",List.of(),"usedRunRefs",List.of(),"answerSnapshot",Map.of("implementationId","v1","kind","explain_concept","summary","설명"));
        assertThat(internal(path+"/finalize",mutation(claim,"answer",answer)).get("status").stringValue()).isEqualTo("COMPLETED");
    }
    @Test void deletingPinnedRunCancelsWorkAndPreventsLateFinalization() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/context",mutation(claim,"requiredRunRefs",List.of(refs.getFirst())));
        var deletion=send("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);assertThat(deletion.statusCode()).describedAs(deletion.body()).isEqualTo(200);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(internalResponse(path+"/checkpoint",mutation(claim,"payload",Map.of("late",true))).statusCode()).isEqualTo(409);
    }
    @Test void priorFailureIsHiddenOnceAnotherRequestIsAccepted() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/fail",mutation(claim,"error",Map.of("code","MODEL_UNAVAILABLE","message","모델 연결 실패")));
        assertThat(state().get("failedAgentRequest").get("requestId")).isEqualTo(job.get("requestId"));accepted();
        assertThat(state().get("failedAgentRequest").isNull()).isTrue();
    }
    @Test void failedExplanationRejectsUnvalidatedPartialAndNeverExposesRawDraft() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claim,"operationKind","explain_change"));
        var failure=mutation(claim,"error",Map.of("code","MODEL_UNAVAILABLE","message","모델 연결 실패"));failure.put("partialResult",Map.of("explanationComplete",false));failure.put("usedRunRefs",refs.subList(0,2));
        assertThat(internalResponse(path+"/fail",failure).statusCode()).isEqualTo(400);
        assertThat(ok("GET","/api/agent"+path,null,null).get("partialResult").isNull()).isTrue();
    }
    @Test void deletingRunFromOldAnswerDoesNotBlockUnrelatedNewQuery() throws Exception {
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",turn()),"old-answer");
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        var job=accepted();var claim=claim();
        var context=internal("/requests/"+job.get("requestId").stringValue()+"/context",mutation(claim,"requiredRunRefs",List.of()));
        assertThat(context.get("runs").size()).isEqualTo(3);
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
    }
}
