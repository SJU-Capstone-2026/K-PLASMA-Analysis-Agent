package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.assertThat;

/** Isolated Testcontainers database; every Run and record is artificial. No model calls. */
@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class V3RuntimeContractTest extends WorkspaceTestSupport {
    @Test void versionAndOptionsArePinnedAndLegacyWorkersCannotTakeTheRequest() throws Exception {
        var body=Map.of("text","인공 기록 질문","stateToken",token(),"graphVersion","v3",
            "v3Options",Map.of("rulesEnabled",true,"ragEnabled",false));
        var accepted=ok("POST","/api/agent/requests",body,"v3-modes");
        assertThat(accepted.path("v3Options").path("rulesEnabled").asBoolean()).isTrue();
        assertThat(accepted.path("v3Options").path("ragEnabled").asBoolean()).isFalse();
        assertThat(accepted.path("v3Options").path("configDigest").asString()).hasSize(64);
        assertThat(ok("POST","/api/agent/requests",body,"v3-modes").get("requestId")).isEqualTo(accepted.get("requestId"));
        var changed=new LinkedHashMap<String,Object>(body);changed.put("v3Options",Map.of("rulesEnabled",true,"ragEnabled",true));
        assertThat(send("POST","/api/agent/requests",changed,"v3-modes").statusCode()).isEqualTo(409);
        assertThat(internal("/claim",Map.of("workerId","legacy","leaseSeconds",60,"supportedGraphVersions",List.of("v1","v2"))).path("request").isNull()).isTrue();
        var claim=internal("/claim",Map.of("workerId","v3","leaseSeconds",60,"supportedGraphVersions",List.of("v3")));
        assertThat(claim.path("request").path("v3Options")).isEqualTo(accepted.path("v3Options"));
        var publicView=ok("GET","/api/agent/requests/"+accepted.path("requestId").asString(),null,null);
        assertThat(publicView.path("v3Options")).isEqualTo(accepted.path("v3Options"));
    }
    @Test void v3OptionsAreRequiredAndForbiddenOnLegacyRequests() throws Exception {
        assertThat(send("POST","/api/agent/requests",Map.of("text","질문","stateToken",token(),"graphVersion","v3"),"missing-mode").statusCode()).isEqualTo(400);
        assertThat(send("POST","/api/agent/requests",Map.of("text","질문","stateToken",token(),"graphVersion","v2",
            "v3Options",Map.of("rulesEnabled",true,"ragEnabled",false)),"legacy-mode").statusCode()).isEqualTo(400);
    }
    @Test void disabledRagIsRejectedBeforeAPlanOrExecutionIsPersisted() throws Exception {
        var request=ok("POST","/api/agent/requests",Map.of("text","이 Run의 이전 기록을 찾아줘","stateToken",token(),"graphVersion","v3",
            "v3Options",Map.of("rulesEnabled",true,"ragEnabled",false)),"disabled-rag");
        var claim=internal("/claim",Map.of("workerId","v3","leaseSeconds",60,"supportedGraphVersions",List.of("v3")));
        String path="/requests/"+request.path("requestId").asString();
        var fence=fence(claim);
        var draft=new LinkedHashMap<String,Object>();draft.put("schema_version",2);draft.put("base_revision",null);
        draft.put("request_mode","data_request");draft.put("requirements",List.of());
        draft.put("steps",List.of(Map.of("id","records","kind","tool","tool","decision_records",
            "inputs",Map.of("action","search","runs",Map.of("kind","context_ref","key","activeRun"),
                "query","이 Run의 이전 기록을 찾아줘","source",Map.of("message_key","current","quote","이 Run의 이전 기록을 찾아줘")))));
        fence.put("payload",draft);
        assertThat(sendInternal(path+"/plans",fence).statusCode()).isEqualTo(400);
        assertThat(jdbc.queryForObject("select count(*) from agent_v2_plan_revision where request_id=?::uuid",Integer.class,request.path("requestId").asString())).isZero();
        assertThat(jdbc.queryForObject("select count(*) from agent_step_execution where request_id=?::uuid",Integer.class,request.path("requestId").asString())).isZero();
    }
    @Test void recordReadUsesConfirmedVersionsAndRetainsComparisonProvenance() throws Exception {
        var record=review();record.set("comparedRunIds",mapper.valueToTree(List.of(refs.get(1).path("runId").asString())));
        record.set("comparedRunRefs",mapper.valueToTree(List.of(refs.get(1))));
        record.set("runSnapshots",mapper.valueToTree(List.of(snapshot(0,false),snapshot(1,false))));
        ok("POST","/api/decisions",write(record),"v3-record");
        var selection=new LinkedHashMap<String,Object>();selection.put("stateToken",token());selection.put("activeRun",refs.get(1));selection.put("candidateReference",null);
        ok("PUT","/api/workspace/reference",selection,null);
        var request=ok("POST","/api/agent/requests",Map.of("text","이 Run의 비교 참조 기록을 찾아줘","stateToken",token(),"graphVersion","v3",
            "v3Options",Map.of("rulesEnabled",false,"ragEnabled",true)),"v3-record-scope");
        var claim=internal("/claim",Map.of("workerId","v3","leaseSeconds",60,"supportedGraphVersions",List.of("v3")));
        String path="/requests/"+request.path("requestId").asString();var body=fence(claim);
        var draft=new LinkedHashMap<String,Object>();draft.put("schema_version",2);draft.put("base_revision",null);draft.put("request_mode","data_request");draft.put("requirements",List.of());
        draft.put("steps",List.of(Map.of("id","records","kind","tool","tool","decision_records","inputs",Map.of("action","search"))));
        body.put("payload",draft);internal(path+"/plans",body);
        body.put("planRevision",1);body.put("stepId","records");body.put("payload",Map.of("runs",List.of(refs.get(1)),"action","search","query","이 Run의 비교 참조 기록을 찾아줘"));
        String execution=internal(path+"/steps",body).path("executionId").asString();
        var records=internal(path+"/steps/"+execution+"/decision-records",fence(claim)).path("records");
        assertThat(records).hasSize(1);assertThat(records.get(0).path("comparedRunRefs").get(0)).isEqualTo(refs.get(1));
        assertThat(records.get(0).has("authorName")).isFalse();
        assertThat(records.get(0).path("targetRunRef")).isEqualTo(refs.get(0));
    }
    private Map<String,Object> fence(JsonNode claim) {return new LinkedHashMap<>(Map.of("claimGeneration",claim.get("claimGeneration"),"requestRevision",claim.get("requestRevision")));}
    private JsonNode internal(String path,Map<String,?> body)throws Exception {
        var response=sendInternal(path,body);assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);
    }
    private HttpResponse<String> sendInternal(String path,Map<String,?> body)throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+path))
            .header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        return HttpClient.newHttpClient().send(request,HttpResponse.BodyHandlers.ofString());
    }
}
