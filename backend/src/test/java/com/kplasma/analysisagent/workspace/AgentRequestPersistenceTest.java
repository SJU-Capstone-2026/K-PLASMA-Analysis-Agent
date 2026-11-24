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
        var chosen=refs.subList(0,size);
        var reference=new HashMap<String,Object>();
        reference.put("stateToken",token());reference.put("activeRun",null);
        reference.put("candidateReference",Map.of("kind","후보 집합","runs",chosen,"catalogRefs",chosen));
        ok("PUT","/api/workspace/reference",reference,null);
        var origins=chosen.stream().map(ref->Map.of("ref",ref,"kind","catalog_tag")).toList();
        var job=ok("POST","/api/agent/requests",Map.of("text","선택한 실험 비교","stateToken",token(),"attachedRunRefs",chosen,"referenceOrigins",origins),"bulk-request");
        var claimed = claim();
        String path = "/requests/" + job.get("requestId").asString();
        String step = reserveStep(path, claimed, "compare_runs", Map.of("runs", chosen));
        clearInvocations(observedJdbc);
        var context = internal(step + "/context", fence(claimed));
        var runReads = mockingDetails(observedJdbc).getInvocations().stream()
            .filter(call -> call.getArguments().length == 3
                && call.getArguments()[1] instanceof org.springframework.jdbc.core.RowMapper<?>
                && call.getArguments()[0] instanceof String sql
                && sql.startsWith("select") && sql.contains("from run_version")).toList();
        assertThat(runReads).hasSize(2);
        assertThat(context.get("runs").size()).isEqualTo(size);
        assertThat(internal(step + "/context", fence(claimed))).isEqualTo(context);
        clearInvocations(observedJdbc);
        for (int offset = 0; offset < size; offset += 25) {
            var batch = chosen.subList(offset, Math.min(offset + 25, size));
            var outputInput = new HashMap<>(fence(claimed));
            outputInput.put("runRefs", batch);
            outputInput.put("plotIds", List.of("current", "residual"));
            var response = internal(step + "/comparison-outputs", outputInput);
            assertThat(response.get("outputs").size()).isEqualTo(batch.size() * 2);
            response.get("outputs").forEach(output -> assertThat(output.get("display").isNull()).isTrue());
        }
        var outputSql=mockingDetails(observedJdbc).getInvocations().stream()
            .filter(call->call.getMethod().getParameterCount()==3
                && call.getMethod().getParameterTypes()[1]==org.springframework.jdbc.core.RowCallbackHandler.class
                && call.getArguments()[0] instanceof String sql && sql.contains("run_output_snapshot"))
            .map(call->(String)call.getArguments()[0]).toList();
        assertThat(outputSql).hasSize((size+24)/25)
            .allSatisfy(sql->assertThat(sql).doesNotContain("source_file", "o.display"));
        System.out.printf("Comparison output snapshot SQL: runs=%d batches=%d statements=%d%n",size,(size+24)/25,outputSql.size());
    }
    @Test void frozenRunOptionsResumePinsOnlySelectedVersions() throws Exception {
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","compare_runs"));
        internal(path+"/needs-input",mutation(claimed,"pendingInput",Map.of("type","run_selection","id","pick","message","비교할 실험을 선택해 주세요","minSelections",2,"baselineRequired",false,"optionsUrl","/api/agent"+path+"/run-options?pendingInputId=pick")));
        var options=ok("GET","/api/agent"+path+"/run-options?pendingInputId=pick",null,null);
        assertThat(options.get("options").size()).isEqualTo(4);
        var input=Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","runKeys",List.of("R1","R3")));
        var resumed=ok("POST","/api/agent"+path+"/resume",input,"pick-input");
        assertThat(resumed.get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(state().get("agentMessages").get(0).get("submittedRunRefs").size()).isZero();
        var next = claim();
        var entries = next.path("context").path("comparisonReference").path("entries");
        var selected = List.of(options.path("options").get(0).path("ref"), options.path("options").get(2).path("ref"));
        assertThat(entries).hasSize(2);
        assertThat(entries.get(0).path("ref")).isEqualTo(selected.get(0));
        assertThat(entries.get(1).path("ref")).isEqualTo(selected.get(1));
        String step = reserveStep(path, next, "compare_runs", Map.of("runs", selected));
        assertThat(internal(step + "/context", fence(next)).path("runs")).hasSize(2);
        assertThat(ok("POST","/api/agent"+path+"/resume",input,"pick-input").get("requestId")).isEqualTo(resumed.get("requestId"));
    }
    @Test void deletedUnselectedVersionIsDisabledAndOnlySelectedDeletionCancelsComparison()throws Exception{
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","compare_runs"));
        internal(path+"/needs-input",mutation(claimed,"pendingInput",Map.of("type","run_selection","id","pick","message","실험 선택","minSelections",2,"baselineRequired",false)));
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-3")),null);
        var options=ok("GET","/api/agent"+path+"/run-options?pendingInputId=pick",null,null);
        assertThat(options.get("options").size()).isEqualTo(4);
        assertThat(options.get("options").get(3).get("selectable").asBoolean()).isFalse();
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
        var answer=v2GeneralAnswer("설명해줘","개념 설명");
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
    private JsonNode claim() throws Exception {return internal("/claim",Map.of("workerId","test-worker","leaseSeconds",60,"supportedGraphVersions",List.of("v2")));}
    private String reserveStep(String path, JsonNode claim, String tool, Map<String,Object> inputs) throws Exception {
        var draft = new LinkedHashMap<String,Object>();
        draft.put("schema_version", 1);
        draft.put("base_revision", null);
        draft.put("steps", List.of(Map.of("id", "lookup", "kind", "tool", "tool", tool)));
        internal(path + "/plans", mutation(claim, "payload", draft));
        var body = mutation(claim, "payload", inputs);
        body.put("stepId", "lookup");
        body.put("planRevision", 1);
        return path + "/steps/" + internal(path + "/steps", body).path("executionId").asString();
    }
    @Test void acceptedRequestIsDurableAndExactRetryCreatesOnlyOneJob() throws Exception {
        var body=Map.of("text","이온 플럭스를 설명해줘","stateToken",token());
        var accepted=ok("POST","/api/agent/requests",body,"request-a");
        assertThat(accepted.get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(ok("POST","/api/agent/requests",body,"request-a").get("requestId")).isEqualTo(accepted.get("requestId"));
        assertThat(state().get("activeAgentRequest").get("requestId")).isEqualTo(accepted.get("requestId"));
        var message=state().get("agentMessages").get(0);
        assertThat(message.get("clientMessageId").stringValue()).isEqualTo("request-a");
        assertThat(message.get("question").stringValue()).isEqualTo("이온 플럭스를 설명해줘");
        assertThat(message.get("requestId")).isEqualTo(accepted.get("requestId"));
        assertThat(state().get("agentMessages").size()).isEqualTo(1);
        var claim=internal("/claim",Map.of("workerId","test-worker","leaseSeconds",60,"supportedGraphVersions",List.of("v2")));
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
        var answer=v2GeneralAnswer("설명해줘","개념 설명");
        var completed=internal(path+"/finalize",mutation(claim,"answer",answer));assertThat(completed.get("status").stringValue()).isEqualTo("COMPLETED");
        assertThat(internal(path+"/finalize",mutation(claim,"answer",answer))).isEqualTo(completed);
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from agent_checkpoint where request_id=?",Long.class,UUID.fromString(job.get("requestId").stringValue()))).isZero();
        var changed=new HashMap<>(answer);changed.put("status","CHANGED");assertThat(internalResponse(path+"/finalize",mutation(claim,"answer",changed)).statusCode()).isEqualTo(409);
    }
    @Test void backgroundAnswerIsSavedToItsOriginalConversation() throws Exception {
        long first=token().get("conversationEpoch").longValue();
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        var otherToken=token();
        internal(path+"/heartbeat",mutation(claimed,"operationKind","explain_concept"));
        var answer=v2GeneralAnswer("설명해줘","원래 방의 설명");
        assertThat(internal(path+"/finalize",mutation(claimed,"answer",answer)).get("status").stringValue()).isEqualTo("COMPLETED");
        assertThat(state().get("conversation").get("turns").size()).isZero();
        assertThat(state().get("agentMessages").size()).isZero();
        assertThat(token()).isEqualTo(otherToken);
        var restored=ok("POST","/api/workspace/conversations/"+first+"/activate",Map.of("stateToken",token()),null);
        assertThat(restored.get("conversation").get("turns").get(0).get("id")).isEqualTo(job.get("requestId"));
        assertThat(restored.get("agentMessages").get(0).get("status").stringValue()).isEqualTo("COMPLETED");
    }
    @Test void resetFencesLateWriterAndErasesAllTransientUserContent() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        internal(path+"/checkpoint",mutation(claim,"payload",Map.of("draft","private-state")));
        ok("POST","/api/workspace/reset",Map.of("stateToken",token()),null);
        assertThat(internalResponse(path+"/checkpoint",mutation(claim,"payload",Map.of("draft","late"))).statusCode()).isEqualTo(409);
        var cleared=ok("GET","/api/agent"+path,null,null);assertThat(cleared.get("question").isNull()).isTrue();assertThat(cleared.get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(cleared.get("error").isNull()).isTrue();
        assertThat(state().get("activeAgentRequest").isNull()).isTrue();assertThat(jdbc.queryForObject("select count(*) from agent_checkpoint",Long.class)).isZero();
    }
    @Test void retiredRequestScopedWorkerRoutesAreAbsent() throws Exception {
        var job = accepted();
        var claim = claim();
        String path = "/requests/" + job.path("requestId").asString();
        for (String suffix : List.of("/attempt", "/context", "/comparison-outputs", "/decision-records"))
            assertThat(internalResponse(path + suffix, fence(claim)).statusCode()).isEqualTo(404);
        assertThat(send("GET", "/internal/agent" + path + "/context?claimGeneration=1&requestRevision=0",
            null, null).statusCode()).isEqualTo(404);
        assertThat(internal(path + "/checkpoint", mutation(claim, "payload", Map.of("cursor", 1))).isObject()).isTrue();
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
    @Test void stepContextKeepsPinnedCatalogVersionsAcrossReads() throws Exception {
        var job = accepted();
        var claim = claim();
        String step = reserveStep("/requests/" + job.path("requestId").asString(), claim, "forward_lookup", Map.of());
        var first = internal(step + "/context", fence(claim)).path("runs");
        assertThat(first).hasSize(4);
        assertThat(first.get(0).has("sourceFiles")).isFalse();
        assertThat(first.get(0).has("iedDistribution")).isFalse();
        UUID newer = UUID.randomUUID();
        String old = refs.getFirst().path("runVersionId").asString();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),jsonb_set(summary,'{runVersionId}',to_jsonb(?::text)),jsonb_set(full_run,'{runVersionId}',to_jsonb(?::text)) from run_version where id=?",
            newer, newer.toString(), newer.toString(), UUID.fromString(old));
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'", newer);
        assertThat(internal(step + "/context", fence(claim)).path("runs")).isEqualTo(first);
    }
    @Test void legacyConversationStaysReadableAndCannotEnqueueNewWork() throws Exception {
        var saved=turn();
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",saved),"legacy-turn");
        var rejected=send("POST","/api/agent/requests",Map.of("text","설명해줘","stateToken",token()),"retired-graph");
        assertThat(rejected.statusCode()).isEqualTo(409);
        assertThat(json(rejected).path("code").asString()).isEqualTo("GRAPH_VERSION_RETIRED");
        assertThat(state().path("conversation").path("turns").get(0).path("answerSnapshot")).isEqualTo(saved.path("answerSnapshot"));
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        assertThat(accepted().path("graphVersion").asString()).isEqualTo("v2");
    }
    @Test void workerTokenIsRequiredAndUiOnlyRevisionChangesDoNotInvalidateFinalizer() throws Exception {
        assertThat(send("POST","/internal/agent/claim",Map.of("workerId","unauthorized","leaseSeconds",60),null).statusCode()).isEqualTo(401);
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        var t=turn();ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",t),"unrelated-turn");
        ok("PATCH","/api/workspace/turns/"+t.get("id").stringValue()+"/ui",Map.of("stateToken",token(),"ui",Map.of("collapsed",true)),null);
        var answer=v2GeneralAnswer("설명해줘","설명");
        assertThat(internal(path+"/finalize",mutation(claim,"answer",answer)).get("status").stringValue()).isEqualTo("COMPLETED");
    }
    @Test void deletingPinnedRunCancelsWorkAndPreventsLateFinalization() throws Exception {
        var job=accepted();var claim=claim();String path="/requests/"+job.get("requestId").stringValue();
        String step = reserveStep(path, claim, "forward_lookup", Map.of());
        internal(step + "/context", fence(claim));
        var deletion=send("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);assertThat(deletion.statusCode()).describedAs(deletion.body()).isEqualTo(200);
        assertThat(ok("GET","/api/agent"+path,null,null).get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(internalResponse(path+"/checkpoint",mutation(claim,"payload",Map.of("late",true))).statusCode()).isEqualTo(409);
    }
    @ParameterizedTest @ValueSource(strings={"MODEL_HTTP_401","MODEL_HTTP_503"})
    void httpModelFailureCodesArePersistedAndVisible(String code) throws Exception {
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        var error=Map.of("code",code,"message","모델 API 요청을 완료하지 못했습니다.");
        var failed=internal(path+"/fail",mutation(claimed,"error",error));
        assertThat(failed.get("status").stringValue()).isEqualTo("FAILED");
        assertThat(failed.get("error")).isEqualTo(mapper.valueToTree(error));
        assertThat(ok("GET","/api/agent"+path,null,null).get("error")).isEqualTo(mapper.valueToTree(error));
        assertThat(state().get("failedAgentRequest").get("error")).isEqualTo(mapper.valueToTree(error));
    }
    @Test void publicFailureCodesKeepCharacterAndLengthLimits() throws Exception {
        var job=accepted();var claimed=claim();String path="/requests/"+job.get("requestId").stringValue();
        for(String code:List.of("MODEL HTTP_401","MODEL_HTTP_401!","MODEL_HTTP_401\n","model_HTTP_401","","A".repeat(81))) {
            var response=internalResponse(path+"/fail",mutation(claimed,"error",Map.of("code",code,"message","모델 API 오류")));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(400);
            assertThat(json(response).get("code").stringValue()).isEqualTo("INVALID_AGENT_REQUEST");
        }
        var running=ok("GET","/api/agent"+path,null,null);
        assertThat(running.get("status").stringValue()).isEqualTo("RUNNING");
        assertThat(running.get("error").isNull()).isTrue();
        String maximum="A".repeat(80);
        var failed=internal(path+"/fail",mutation(claimed,"error",Map.of("code",maximum,"message","모델 API 오류")));
        assertThat(failed.get("error").get("code").stringValue()).isEqualTo(maximum);
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
        assertThat(state().get("conversation").get("turns").size()).isEqualTo(1);
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        var job=accepted();var claim=claim();
        String step = reserveStep("/requests/" + job.path("requestId").asString(), claim, "forward_lookup", Map.of());
        var context = internal(step + "/context", fence(claim));
        assertThat(context.get("runs").size()).isEqualTo(3);
    }
}
