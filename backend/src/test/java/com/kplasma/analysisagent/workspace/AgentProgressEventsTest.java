package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class AgentProgressEventsTest extends WorkspaceTestSupport {
    private JsonNode accepted(String version) throws Exception {
        return ok("POST","/api/agent/requests",Map.of("text","인공 설명","stateToken",token(),"graphVersion",version),UUID.randomUUID().toString());
    }
    private JsonNode claim() throws Exception {return internal("/claim",Map.of("workerId","synthetic","leaseSeconds",60,"supportedGraphVersions",List.of("v1","v2")));}
    private String path(JsonNode request) {return "/requests/"+request.path("requestId").asString();}
    private Map<String,Object> mutation(JsonNode claim,String field,Object value) {
        var body=new LinkedHashMap<String,Object>();body.put("claimGeneration",claim.path("claimGeneration").longValue());body.put("requestRevision",claim.path("requestRevision").longValue());body.put(field,value);return body;
    }
    private HttpResponse<String> internalResponse(String path,Object body) throws Exception {
        return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+path))
            .header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    private JsonNode internal(String path,Object body) throws Exception {var response=internalResponse(path,body);assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);}
    private Map<String,Object> event(JsonNode claim,String key,String type,Object payload) {
        var body=mutation(claim,"payload",payload);body.put("eventKey",key);body.put("type",type);return body;
    }
    private JsonNode start(JsonNode request,JsonNode claim,String stream) throws Exception {
        return internal(path(request)+"/events",event(claim,"r0:"+stream+":start","answer.start",Map.of("streamId",stream,"mode","general","rewrite",false)));
    }
    private Map<String,Object> answer() {return Map.of("intent","CONCEPT_EXPLANATION","status","SUCCESS","candidates",List.of(),"usedRunRefs",List.of(),
        "answerSnapshot",Map.of("implementationId","v1","kind","explain_concept","summary","인공 설명"));}

    @ParameterizedTest @ValueSource(strings={"run_selection","baseline","condition"})
    void lifecycleActivitiesPairAcrossClaimGenerationsAndCloseInputWaitsOnResume(String inputKind) throws Exception {
        var job=accepted("v1");var claimed=claim();String path=path(job);
        assertPaired(claimed.path("request"),"QUEUED",0);
        Map<String,Object> pending=new LinkedHashMap<>(Map.of("id","input-1","message","인공 입력 요청"));
        Map<String,Object> input;
        String code;
        if("run_selection".equals(inputKind)) {
            pending.put("type","run_selection");input=Map.of("type","run_selection","runKeys",List.of("R1","R2"));code="NEEDS_RUNS";
        } else if("baseline".equals(inputKind)) {
            pending.put("type","comparison_options");pending.put("fields",List.of("baselineKey"));
            pending.put("allowedRunKeys",List.of("R1","R2"));pending.put("allowedTrendAxes",List.of("pressure"));
            input=Map.of("type","comparison_options","baselineKey","R1");code="NEEDS_BASELINE";
        } else {pending.put("type","condition");input=Map.of("text","인공 조건");code="NEEDS_CONDITIONS";}
        internal(path+"/needs-input",mutation(claimed,"pendingInput",pending));
        var resumed=ok("POST","/api/agent"+path+"/resume",Map.of("expectedRequestRevision",0,"pendingInputId","input-1","input",input),"lifecycle-resume");
        assertPaired(resumed,code,0);
        var events=ok("GET","/api/agent"+path+"/events?format=json",null,null).path("events");
        for(var event:events)if("activity".equals(event.path("type").asString()) && code.equals(event.path("payload").path("code").asString()))
            assertThat(event.path("requestRevision").longValue()).isZero();
        var next=claim();assertPaired(next.path("request"),"RESUMED",1);
        assertThat(next.path("claimGeneration").longValue()).isGreaterThan(claimed.path("claimGeneration").longValue());
    }
    private void assertPaired(JsonNode request,String code,long revision) {
        var activities=new ArrayList<JsonNode>();
        for(var activity:request.path("progress").path("activities"))if(code.equals(activity.path("code").asString()))activities.add(activity);
        assertThat(activities).hasSize(2);
        assertThat(activities.getFirst().path("phase").asString()).isEqualTo("started");
        assertThat(activities.getLast().path("phase").asString()).isEqualTo("completed");
        assertThat(activities.getLast().path("activityId")).isEqualTo(activities.getFirst().path("activityId"));
        assertThat(activities.getLast().path("activityId").asString()).isEqualTo("system:"+revision+":"+code);
    }

    @Test void durableOrderExactReplaySnapshotsAndAnswerFences() throws Exception {
        var job=accepted("v1");var claim=claim();String path=path(job);
        var started=start(job,claim,"draft-1");long revision=started.path("payload").path("answerRevision").longValue();
        var delta=event(claim,"r0:draft:chunk0","answer.delta",Map.of("streamId","draft-1","answerRevision",revision,"blockId","paragraphs:0","text","첫 본문","chunkIndex",0));
        var first=internal(path+"/events",delta);
        assertThat(internal(path+"/events",delta)).isEqualTo(first);
        var changed=event(claim,"r0:draft:chunk0","answer.delta",Map.of("streamId","draft-1","answerRevision",revision,"blockId","paragraphs:0","text","다른 본문","chunkIndex",0));
        assertThat(internalResponse(path+"/events",changed).statusCode()).isEqualTo(409);
        assertThat(first.path("workspaceEpoch")).isEqualTo(job.path("workspaceEpoch"));
        assertThat(first.path("conversationEpoch")).isEqualTo(job.path("conversationEpoch"));
        var status=ok("GET","/api/agent"+path,null,null);long cursor=status.path("progress").path("lastEventSeq").longValue();
        assertThat(cursor).isEqualTo(first.path("seq").longValue());
        assertThat(status.path("progress").path("answer").path("blocks").get(0).path("text").asString()).isEqualTo("첫 본문");
        var events=ok("GET","/api/agent"+path+"/events?format=json&after=0",null,null);
        for(int i=0;i<events.path("events").size();i++)assertThat(events.path("events").get(i).path("seq").longValue()).isEqualTo(i+1L);
        assertThat(events.path("lastEventSeq").longValue()).isEqualTo(cursor);
        internal(path+"/events",event(claim,"r0:draft:reset","answer.reset",Map.of("streamId","draft-1","answerRevision",revision,"reason","REWRITE")));
        start(job,claim,"draft-2");
        assertThat(internalResponse(path+"/events",event(claim,"r0:draft:late","answer.delta",Map.of("streamId","draft-1","answerRevision",revision,"blockId","paragraphs:0","text","늦은 조각","chunkIndex",1))).statusCode()).isEqualTo(409);
        jdbc.update("update agent_request set lease_until=clock_timestamp()-interval '1 second' where id=?::uuid",job.path("requestId").asString());
        assertThat(internalResponse(path+"/events",delta).statusCode()).isEqualTo(409);
    }

    @Test void runningTimeExcludesInputAndQueueAndIsStableAfterFinalization() throws Exception {
        var job=accepted("v1");var claim=claim();String path=path(job);String id=job.path("requestId").asString();
        jdbc.update("update agent_request set running_started_at=clock_timestamp()-interval '5 seconds' where id=?::uuid",id);
        internal(path+"/needs-input",mutation(claim,"pendingInput",Map.of("id","input-1","message","조건을 알려주세요","type","condition")));
        long first=jdbc.queryForObject("select running_duration_ms from agent_request where id=?::uuid",Long.class,id);
        assertThat(first).isBetween(5000L,6500L);
        jdbc.update("update agent_request set updated_at=clock_timestamp()-interval '2 days' where id=?::uuid",id);
        ok("POST","/api/agent"+path+"/resume",Map.of("expectedRequestRevision",0,"pendingInputId","input-1","input",Map.of("text","10 mTorr")),"input-reply");
        assertThat(jdbc.queryForObject("select running_duration_ms from agent_request where id=?::uuid",Long.class,id)).isEqualTo(first);
        var next=claim();jdbc.update("update agent_request set running_started_at=clock_timestamp()-interval '2 seconds' where id=?::uuid",id);
        var completed=internal(path+"/finalize",mutation(next,"answer",answer()));
        long duration=completed.path("executionSummary").path("durationMs").longValue();
        assertThat(duration).isBetween(first+2000,first+3500);
        assertThat(internal(path+"/finalize",mutation(next,"answer",answer()))).isEqualTo(completed);
        assertThat(state().path("agentMessages").get(0).path("executionSummary").path("durationMs").longValue()).isEqualTo(duration);
        var page=ok("GET","/api/agent"+path+"/events?format=json&after=0",null,null);
        var last=page.path("events").get(page.path("events").size()-1);
        assertThat(last.path("type").asString()).isEqualTo("request.state");
        assertThat(last.path("payload").path("durationMs").longValue()).isEqualTo(duration);
    }

    @Test void recoveryClampsAbandonedIntervalToItsLeaseAndLegacyDurationsStayUnknown() throws Exception {
        var job=accepted("v1");var old=claim();String path=path(job);String id=job.path("requestId").asString();
        start(job,old,"lost-draft");
        jdbc.update("update agent_request set running_started_at=clock_timestamp()-interval '10 seconds',lease_until=clock_timestamp()-interval '5 seconds' where id=?::uuid",id);
        var fresh=claim();
        long recovered=jdbc.queryForObject("select running_duration_ms from agent_request where id=?::uuid",Long.class,id);
        assertThat(recovered).isBetween(4999L,5001L);
        assertThat(fresh.path("request").path("progress").path("answer").path("status").asString()).isEqualTo("interrupted");
        assertThat(internalResponse(path+"/events",event(old,"late-old","activity",Map.of("activityId","late","code","PLAN","phase","started"))).statusCode()).isEqualTo(409);
        jdbc.update("update agent_request set running_duration_ms=null where id=?::uuid",id);
        var completed=internal(path+"/finalize",mutation(fresh,"answer",answer()));
        assertThat(completed.has("executionSummary")).isFalse();
    }

    @Test void openSseDoesNotHoldRequestLocksAndTerminalReplayStopsReconnection() throws Exception {
        var job=accepted("v1");var claimed=claim();String path=path(job);
        var client=HttpClient.newHttpClient();
        var stream=client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/agent"+path+"/events"))
            .header("Accept","text/event-stream").header("Last-Event-ID",job.path("progress").path("lastEventSeq").asString())
            .GET().build(),HttpResponse.BodyHandlers.ofInputStream());
        assertThat(stream.statusCode()).isEqualTo(200);assertThat(stream.headers().firstValue("content-type").orElse("")).startsWith("text/event-stream");
        var reader=new java.io.BufferedReader(new java.io.InputStreamReader(stream.body(),java.nio.charset.StandardCharsets.UTF_8));
        assertThat(reader.readLine()).isEqualTo("id:"+(job.path("progress").path("lastEventSeq").longValue()+1));
        var normal=client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/agent"+path)).timeout(Duration.ofSeconds(3)).GET().build(),HttpResponse.BodyHandlers.ofString());
        assertThat(normal.statusCode()).isEqualTo(200);
        assertThat(send("GET","/api/runs",null,null).statusCode()).isEqualTo(200);
        var completed=internal(path+"/finalize",mutation(claimed,"answer",answer()));
        stream.body().close();
        long cursor=completed.path("progress").path("lastEventSeq").longValue();
        var finalStream=client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/agent"+path+"/events?after="+(cursor-1)))
            .timeout(Duration.ofSeconds(3)).GET().build(),HttpResponse.BodyHandlers.ofString());
        assertThat(finalStream.statusCode()).isEqualTo(200);assertThat(finalStream.body()).contains("request.state").contains("COMPLETED");
        var done=client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/agent"+path+"/events"))
            .header("Last-Event-ID",Long.toString(cursor)).GET().build(),HttpResponse.BodyHandlers.ofString());
        assertThat(done.statusCode()).isEqualTo(204);assertThat(done.body()).isEmpty();
    }

    @Test void cancelAndResetFenceLateEventsAndEraseAllPublicContent() throws Exception {
        var job=accepted("v1");var claimed=claim();String path=path(job);start(job,claimed,"private-draft");
        var cancelled=ok("POST","/api/agent"+path+"/cancel",null,null);
        assertThat(cancelled.path("progress").path("answer").path("status").asString()).isEqualTo("interrupted");
        assertThat(cancelled.path("executionSummary").path("durationMs").isNumber()).isTrue();
        assertThat(internalResponse(path+"/events",event(claimed,"late","activity",Map.of("activityId","late","code","PLAN","phase","started"))).statusCode()).isEqualTo(409);
        ok("POST","/api/workspace/reset",Map.of("stateToken",token()),null);
        assertThat(send("GET","/api/agent"+path+"/events?format=json",null,null).statusCode()).isEqualTo(404);
        assertThat(send("GET","/api/agent"+path+"/results?resultRevision=1",null,null).statusCode()).isEqualTo(404);
        assertThat(ok("GET","/api/agent"+path,null,null).path("progress").path("lastEventSeq").longValue()).isZero();
        assertThat(jdbc.queryForObject("select count(*) from agent_public_event where request_id=?::uuid",Long.class,job.path("requestId").asString())).isZero();
    }

    @Test void failureToPersistTheCompletionEventRollsBackTurnStatusAndTiming() throws Exception {
        var job=accepted("v1");var claimed=claim();String path=path(job);String id=job.path("requestId").asString();
        long cursor=claimed.path("request").path("progress").path("lastEventSeq").longValue();
        jdbc.execute("""
            create function synthetic_reject_completion() returns trigger language plpgsql as $$
            begin if new.type='request.state' and new.payload->>'status'='COMPLETED' then
                raise exception 'synthetic completion event failure'; end if; return new; end $$
            """);
        jdbc.execute("create trigger synthetic_reject_completion before insert on agent_public_event for each row execute function synthetic_reject_completion()");
        try {
            var rejected=internalResponse(path+"/finalize",mutation(claimed,"answer",answer()));
            assertThat(rejected.statusCode()).isEqualTo(503);assertThat(json(rejected).path("code").asString()).isEqualTo("INTAKE_UNAVAILABLE");
            var unchanged=ok("GET","/api/agent"+path,null,null);
            assertThat(unchanged.path("status").asString()).isEqualTo("RUNNING");
            assertThat(unchanged.path("progress").path("lastEventSeq").longValue()).isEqualTo(cursor);
            assertThat(unchanged.has("executionSummary")).isFalse();
            assertThat(jdbc.queryForObject("select count(*) from conversation_turn where id=?::uuid",Long.class,id)).isZero();
            assertThat(jdbc.queryForObject("select running_started_at is not null and execution_finished_at is null from agent_request where id=?::uuid",Boolean.class,id)).isTrue();
        } finally {
            jdbc.execute("drop trigger synthetic_reject_completion on agent_public_event");jdbc.execute("drop function synthetic_reject_completion()");
        }
        assertThat(internal(path+"/finalize",mutation(claimed,"answer",answer())).path("status").asString()).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("select count(*) from conversation_turn where id=?::uuid",Long.class,id)).isEqualTo(1);
    }

    @Test void resultBindingsUseVerifiedCurrentGraphExecutionsAndOlderVersionsRemainImmutable() throws Exception {
        var job=accepted("v2");var claimed=claim();String path=path(job);
        var step=Map.of("id","lookup","kind","tool","tool","forward_lookup","depends_on",List.of(),"inputs",Map.of("artificial",1));
        var plan=new LinkedHashMap<String,Object>();plan.put("schema_version",1);plan.put("base_revision",null);plan.put("steps",List.of(step));
        internal(path+"/plans",mutation(claimed,"payload",plan));
        var reserve=mutation(claimed,"payload",Map.of());reserve.put("planRevision",1);reserve.put("stepId","lookup");
        var permit=internal(path+"/steps",reserve);String execution=permit.path("executionId").asString();
        var raw=new LinkedHashMap<String,Object>();raw.put("kind","forward_lookup");raw.put("resultStatus","NO_DATA");raw.put("status","NO_DATA");
        raw.put("run",null);raw.put("selectedRun",null);raw.put("candidates",List.of());raw.put("deltas",null);
        raw.put("requestedConditions",Map.of("pressure",1,"sourcePower",10,"biasPower",20));raw.put("units",Map.of("pressure","mTorr","sourcePower","W","biasPower","W"));
        raw.put("usedRunRefs",List.of());raw.put("excludedRuns",List.of());raw.put("defaultedUnits",List.of());raw.put("numericPolicyVersion","v1");raw.put("rawModelOutput","must-never-leak");
        var result=Map.of("executionId",execution,"stepId","lookup","status","empty","outputs",Map.of("toolResult",raw,"candidates",List.of()),"runRefs",List.of());
        assertThat(internalResponse(path+"/events",event(claimed,"before-save","results.ready",Map.of("executionIds",List.of(execution)))).statusCode()).isEqualTo(409);
        internal(path+"/steps/"+execution+"/result",mutation(claimed,"payload",result));
        var ready=internal(path+"/events",event(claimed,"ready-1","results.ready",Map.of("executionIds",List.of(execution))));
        long revision=ready.path("seq").longValue();assertThat(ready.path("payload").path("resultRevision").longValue()).isEqualTo(revision);
        var published=ok("GET","/api/agent"+path+"/results?resultRevision="+revision,null,null);
        assertThat(published.path("results").size()).isEqualTo(1);assertThat(published.toString()).doesNotContain("rawModelOutput","must-never-leak");
        assertThat(published.path("results").get(0).path("executionId").asString()).isEqualTo(execution);
        plan.put("base_revision",1);plan.put("steps",List.of(Map.of("id","lookup","kind","tool","tool","forward_lookup","depends_on",List.of(),"inputs",Map.of("artificial",2))));
        internal(path+"/plans",mutation(claimed,"payload",plan));
        assertThat(internalResponse(path+"/events",event(claimed,"invalidated","results.ready",Map.of("executionIds",List.of(execution)))).statusCode()).isEqualTo(409);
        internal(path+"/events",event(claimed,"ready-2","results.ready",Map.of("executionIds",List.of())));
        assertThat(ok("GET","/api/agent"+path+"/results?resultRevision="+revision,null,null)).isEqualTo(published);
        assertThat(internalResponse(path+"/events",event(claimed,"foreign","results.ready",Map.of("executionIds",List.of(UUID.randomUUID().toString())))).statusCode()).isEqualTo(409);
    }
}
