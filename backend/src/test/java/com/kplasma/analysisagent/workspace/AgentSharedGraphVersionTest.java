package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;

import static org.assertj.core.api.Assertions.assertThat;

@TestPropertySource(properties={"kplasma.agent.worker-token=synthetic-cloud-worker",
    "kplasma.agent.local-worker-token=synthetic-local-worker",
    "kplasma.agent.supported-graph-versions=v2,v2_localLLM", "kplasma.agent.default-graph-version=v2",
    "AGENT_LOCAL_RUNTIME_ENABLED=false", "AGENT_LOCAL_UI_ORIGIN=http://127.0.0.1:5173",
    "AGENT_LOCAL_API_HOST="})
class AgentSharedGraphVersionTest extends WorkspaceTestSupport {

    private HttpResponse<String> exchange(String method, String path, Object body, String worker, String key)
            throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
            .header("Content-Type", "application/json");
        if (worker != null) request.header("X-Agent-Token", worker);
        else request.header("Origin", "http://127.0.0.1:5173").header("Sec-Fetch-Site", "same-site");
        if (key != null) request.header("Idempotency-Key", key);
        return HttpClient.newHttpClient().send(request.method(method, body == null
            ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),
            HttpResponse.BodyHandlers.ofString());
    }

    @Override protected HttpResponse<String> send(String method, String path, Object body, String key) throws Exception {
        return exchange(method, path, body, null, key);
    }

    private HttpResponse<String> claim(String worker, List<String> versions) throws Exception {
        return exchange("POST", "/internal/agent/claim", Map.of("workerId", "synthetic-" + worker,
            "leaseSeconds", 30, "supportedGraphVersions", versions), worker, null);
    }

    private void forbidden(HttpResponse<String> response) {
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(403);
        assertThat(json(response).path("code").asString()).isEqualTo("WORKER_GRAPH_FORBIDDEN");
        assertThat(response.body()).doesNotContain("private-local-question", "private-cloud-question");
    }

    private void assertAllRequestRoutesReject(String worker, JsonNode request) throws Exception {
        String root = "/internal/agent/requests/" + request.path("requestId").asString();
        String dummy = "00000000-0000-0000-0000-000000000001";
        var body = Map.of("claimGeneration", 1, "requestRevision", 0);
        for (String path : List.of("events", "heartbeat", "context", "checkpoint", "plans", "steps",
                "steps/" + dummy + "/context", "steps/" + dummy + "/decision-records",
                "steps/" + dummy + "/comparison-outputs", "steps/" + dummy + "/result",
                "model-attempts", "model-attempts/" + dummy + "/complete", "comparison-outputs",
                "attempt", "decision-records", "needs-input", "fail", "finalize")) {
            forbidden(exchange("POST", root + "/" + path, body, worker, null));
        }
        for (String path : List.of("context", "checkpoint"))
            forbidden(exchange("GET", root + "/" + path + "?claimGeneration=1&requestRevision=0",
                null, worker, null));
    }

    @Test void oneWorkspaceSharesHistoryWhileWorkerKeysKeepModelRoutesSeparate() throws Exception {
        var workspace = send("GET", "/api/workspace", null, null);
        assertThat(workspace.statusCode()).isEqualTo(200);
        assertThat(workspace.headers().firstValue("Set-Cookie")).isEmpty();
        var cloudMemory=review();cloudMemory.put("reviewId","REV-shared-cloud");cloudMemory.put("comment","CLOUD_MEMORY");
        ok("POST","/api/decisions",write(cloudMemory),"cloud-memory");
        var historicalMemory=review();historicalMemory.put("reviewId","REV-retired-v1");
        historicalMemory.put("comment","HISTORICAL_V1_MEMORY");
        ok("POST","/api/decisions",write(historicalMemory),"v1-memory");
        jdbc.update("update decision set origin_graph_version='v1' where review_id='REV-retired-v1'");
        var cloud = ok("POST", "/api/agent/requests", Map.of("text", "private-cloud-question",
            "stateToken", token(), "graphVersion", "v2"), "cloud-question");
        forbidden(claim("synthetic-local-worker", List.of("v2")));
        forbidden(claim("synthetic-cloud-worker", List.of("v2_localLLM")));
        var cloudClaim = claim("synthetic-cloud-worker", List.of("v2"));
        assertThat(cloudClaim.statusCode()).describedAs(cloudClaim.body()).isEqualTo(200);
        assertThat(json(cloudClaim).path("request").path("requestId").asString())
            .isEqualTo(cloud.path("requestId").asString());
        assertAllRequestRoutesReject("synthetic-local-worker", cloud);
        ok("POST", "/api/agent/requests/" + cloud.path("requestId").asString() + "/cancel", Map.of(), "cancel-cloud");
        ok("POST", "/api/workspace/new-conversation", Map.of("stateToken", token()), null);
        var local = ok("POST", "/api/agent/requests", Map.of("text", "private-local-question",
            "stateToken", token(), "graphVersion", "v2_localLLM"), "local-question");
        forbidden(claim("synthetic-cloud-worker", List.of("v2", "v2_localLLM")));
        var noCloudWork = claim("synthetic-cloud-worker", List.of("v2"));
        assertThat(noCloudWork.statusCode()).describedAs(noCloudWork.body()).isEqualTo(200);
        assertThat(json(noCloudWork).path("request").isNull()).isTrue();
        var localClaim = claim("synthetic-local-worker", List.of("v2_localLLM"));
        assertThat(localClaim.statusCode()).describedAs(localClaim.body()).isEqualTo(200);
        assertThat(json(localClaim).path("request").path("requestId").asString())
            .isEqualTo(local.path("requestId").asString());
        assertAllRequestRoutesReject("synthetic-cloud-worker", local);
        assertThat(state().path("conversation").path("agentGraphVersion").asString()).isEqualTo("v2_localLLM");
        assertThat(state().path("conversations").size()).isEqualTo(2);
        var privateMemory=review();privateMemory.put("reviewId","REV-local-private");
        privateMemory.put("comment","LOCAL_ONLY_MEMORY");
        ok("POST","/api/decisions",write(privateMemory),"local-memory");
        assertThat(jdbc.queryForObject("select origin_graph_version from decision where review_id='REV-local-private'",String.class))
            .isEqualTo("v2_localLLM");
        String localRoot="/internal/agent/requests/"+local.path("requestId").asString();
        var localFence=Map.<String,Object>of("claimGeneration",json(localClaim).path("claimGeneration").longValue(),
            "requestRevision",json(localClaim).path("requestRevision").longValue());
        assertThat(exchange("POST",localRoot+"/heartbeat",Map.of("claimGeneration",localFence.get("claimGeneration"),
            "requestRevision",localFence.get("requestRevision"),"operationKind","decision_records"),"synthetic-local-worker",null).statusCode()).isEqualTo(200);
        assertThat(exchange("POST",localRoot+"/context",localFence,"synthetic-local-worker",null).statusCode()).isEqualTo(200);
        var localRecords=exchange("POST",localRoot+"/decision-records",localFence,"synthetic-local-worker",null);
        assertThat(localRecords.statusCode()).describedAs(localRecords.body()).isEqualTo(200);
        assertThat(localRecords.body()).contains("LOCAL_ONLY_MEMORY","CLOUD_MEMORY","HISTORICAL_V1_MEMORY");
        ok("POST","/api/agent/requests/"+local.path("requestId").asString()+"/cancel",Map.of(),"cancel-local");
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        var reuse=ok("POST","/api/agent/requests",Map.of("text","cloud-memory-question","stateToken",token(),"graphVersion","v2"),"cloud-memory-question");
        var reuseClaim=claim("synthetic-cloud-worker",List.of("v2"));
        assertThat(reuseClaim.statusCode()).isEqualTo(200);
        String reuseRoot="/internal/agent/requests/"+reuse.path("requestId").asString();
        var fence=Map.<String,Object>of("claimGeneration",json(reuseClaim).path("claimGeneration").longValue(),
            "requestRevision",json(reuseClaim).path("requestRevision").longValue());
        assertThat(exchange("POST",reuseRoot+"/heartbeat",Map.of("claimGeneration",fence.get("claimGeneration"),
            "requestRevision",fence.get("requestRevision"),"operationKind","decision_records"),"synthetic-cloud-worker",null).statusCode()).isEqualTo(200);
        assertThat(exchange("POST",reuseRoot+"/context",fence,"synthetic-cloud-worker",null).statusCode()).isEqualTo(200);
        var cloudRecords=exchange("POST",reuseRoot+"/decision-records",fence,"synthetic-cloud-worker",null);
        assertThat(cloudRecords.statusCode()).describedAs(cloudRecords.body()).isEqualTo(200);
        assertThat(cloudRecords.body()).contains("CLOUD_MEMORY","HISTORICAL_V1_MEMORY").doesNotContain("LOCAL_ONLY_MEMORY");
        String query="?claimGeneration="+fence.get("claimGeneration")+"&requestRevision="+fence.get("requestRevision");
        assertThat(exchange("GET",reuseRoot+"/context"+query,null,"synthetic-cloud-worker",null).body())
            .contains("CLOUD_MEMORY").doesNotContain("LOCAL_ONLY_MEMORY");
        assertThat(exchange("POST",reuseRoot+"/context",fence,"synthetic-cloud-worker",null).body())
            .doesNotContain("LOCAL_ONLY_MEMORY");
        assertThat(ok("GET","/api/decisions",null,null).toString()).contains("CLOUD_MEMORY","LOCAL_ONLY_MEMORY","HISTORICAL_V1_MEMORY");
        jdbc.update("update agent_request set manifest=jsonb_set(manifest,'{decisionRecords}',?::jsonb) where id=?::uuid",
            mapper.writeValueAsString(List.of(Map.of("reviewId","REV-local-private","comment","LOCAL_ONLY_MEMORY"))),reuse.path("requestId").asString());
        forbidden(exchange("GET",reuseRoot+"/context"+query,null,"synthetic-cloud-worker",null));
        forbidden(exchange("POST",reuseRoot+"/context",fence,"synthetic-cloud-worker",null));
        forbidden(exchange("GET",reuseRoot+"/checkpoint"+query,null,"synthetic-cloud-worker",null));
        jdbc.update("update agent_request set lease_until=clock_timestamp()-interval '1 second' where id=?::uuid",reuse.path("requestId").asString());
        forbidden(claim("synthetic-cloud-worker",List.of("v2")));
        jdbc.update("update decision set origin_graph_version=null where review_id='REV-local-private'");
        forbidden(exchange("GET",reuseRoot+"/checkpoint"+query,null,"synthetic-cloud-worker",null));
        assertThat(ok("GET","/api/decisions",null,null).toString()).contains("LOCAL_ONLY_MEMORY");
    }
}
