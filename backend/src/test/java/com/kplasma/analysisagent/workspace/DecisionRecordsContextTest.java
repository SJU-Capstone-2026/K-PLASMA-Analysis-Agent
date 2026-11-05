package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class DecisionRecordsContextTest extends WorkspaceTestSupport {
    private String path;
    private Map<String,Object> fence;
    private HttpResponse<String> internal(String suffix,Object body,String token) throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+suffix)).header("Content-Type","application/json");
        if(token!=null)request.header("X-Agent-Token",token);
        return HttpClient.newHttpClient().send(request.POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    private HttpResponse<String> internal(String suffix,Object body) throws Exception {return internal(suffix,body,"synthetic-worker-token");}
    private void start(String operationKind) throws Exception {
        var request=ok("POST","/api/agent/requests",Map.of("text","인공 판단 기록 질문","stateToken",token()),UUID.randomUUID().toString());
        path="/requests/"+request.get("requestId").stringValue();
        var claimed=json(internal("/claim",Map.of("workerId","decision-test","leaseSeconds",60)));
        fence=Map.of("claimGeneration",claimed.get("claimGeneration").longValue(),"requestRevision",claimed.get("requestRevision").longValue());
        assertThat(internal(path+"/heartbeat",body(Map.of("operationKind",operationKind))).statusCode()).isEqualTo(200);
    }
    private Map<String,Object> body(Map<String,Object> fields){var body=new HashMap<String,Object>(fence);body.putAll(fields);return body;}
    private void decision(String id,Map<String,Object> record){
        var stored=new LinkedHashMap<String,Object>(record);stored.put("reviewId",id);
        jdbc.update("insert into decision(review_id,workspace_id,record) values (?,1,?::jsonb)",id,mapper.writeValueAsString(stored));
    }
    private Map<String,Object> experiment(String note){
        return Map.of("id","EXP-1","version",2,"authorName","인공 작성자","decision","ADOPT","question","인공 질문","overallComment","인공 공통 코멘트","createdAt","2026-09-20T00:00:00Z",
            "objectives",List.of(Map.of("metric","ionFlux")),
            "candidates",List.of(
                Map.of("runId","SYNTHETIC-0","runVersionId",refs.get(0).get("runVersionId").stringValue(),"decision","ADOPT","note","인공 채택","conditions",Map.of("pressure",6),"metrics",Map.of("ionFlux",1)),
                Map.of("runId","SYNTHETIC-1","runVersionId",refs.get(1).get("runVersionId").stringValue(),"decision","REJECT","note",note,"conditions",Map.of("pressure",8),"metrics",Map.of("ionFlux",2))));
    }
    private JsonNode records() throws Exception {var response=internal(path+"/decision-records",body(Map.of()));assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response).get("records");}

    @Test void returnsOnlyReuseFieldsInSaveOrderAndPinsTheFirstRead() throws Exception {
        decision("EXP-1",experiment("비용이 높아 예산 초과"));
        decision("REV-1",Map.of("targetRunId","SYNTHETIC-1","targetRunRef",refs.get(1),"decision","REJECT","comment","인공 반려","queryText","인공 조회","authorName","인공 작성자",
            "runSnapshots",List.of(Map.of("runId","SYNTHETIC-1","runVersionId",refs.get(1).get("runVersionId").stringValue(),"conditions",Map.of("pressure",8),"metrics",Map.of("ionFlux",2)))));
        start("decision_records");
        assertThat(internal(path+"/context",body(Map.of("requiredRunRefs",List.of(refs.get(1)),"referencesOnly",true))).statusCode()).isEqualTo(200);
        var first=records();
        assertThat(first).hasSize(2);
        assertThat(first.get(0).get("reviewId").stringValue()).isEqualTo("EXP-1");
        assertThat(first.get(1).get("reviewId").stringValue()).isEqualTo("REV-1");
        assertThat(first.get(0).get("candidates").get(1).get("note").stringValue()).isEqualTo("비용이 높아 예산 초과");
        assertThat(first.get(0).get("candidates").get(1).get("conditions").get("pressure").intValue()).isEqualTo(8);
        for(String omitted:List.of("authorName","objectives"))assertThat(first.get(0).has(omitted)).isFalse();
        assertThat(first.get(0).get("candidates").get(1).has("metrics")).isFalse();
        assertThat(first.get(1).get("runSnapshots").get(0).has("metrics")).isFalse();
        decision("EXP-2",experiment("나중에 저장된 인공 기록"));
        assertThat(records()).isEqualTo(first);
        var manifest=mapper.readTree(jdbc.queryForObject("select manifest::text from agent_request where id=?::uuid",String.class,path.substring("/requests/".length())));
        assertThat(manifest.get("decisionRecords")).isEqualTo(first);
    }
    @Test void requiresWorkerFenceRunContextAndRecordOperation() throws Exception {
        decision("EXP-1",experiment("비용이 높아 예산 초과"));
        start("forward_lookup");
        assertThat(internal(path+"/decision-records",body(Map.of()),null).statusCode()).isEqualTo(401);
        assertThat(internal(path+"/decision-records",body(Map.of())).statusCode()).isEqualTo(400);
        assertThat(internal(path+"/heartbeat",body(Map.of("operationKind","reverse_search"))).statusCode()).isEqualTo(200);
        assertThat(internal(path+"/decision-records",body(Map.of())).statusCode()).describedAs("manifest is required first").isEqualTo(400);
        var stale=new HashMap<String,Object>(fence);stale.put("claimGeneration",((Long)fence.get("claimGeneration"))+1);
        assertThat(internal(path+"/decision-records",stale).statusCode()).isEqualTo(409);
    }
}
