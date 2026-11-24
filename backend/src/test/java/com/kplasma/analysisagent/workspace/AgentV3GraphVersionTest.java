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
import tools.jackson.databind.node.ObjectNode;

import static org.assertj.core.api.Assertions.assertThat;

@TestPropertySource(properties={"kplasma.agent.worker-token=synthetic-worker-token",
    "kplasma.agent.supported-graph-versions=v1,v2,v3"})
class AgentV3GraphVersionTest extends WorkspaceTestSupport {
    @Test void v3PinsClaimsFinalizesAndRestoresItsOwnIdentity() throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", "인공 개념 질문", "stateToken", token(), "graphVersion", "v3"), "graph-v3");
        assertThat(request.path("graphVersion").asString()).isEqualTo("v3");
        assertThat(state().path("conversation").path("agentGraphVersion").asString()).isEqualTo("v3");
        var skipped = internal("/claim", Map.of("workerId", "v2-worker", "leaseSeconds", 60, "supportedGraphVersions", List.of("v2")));
        assertThat(skipped.path("request").isNull()).isTrue();
        var claim = internal("/claim", Map.of("workerId", "v3-worker", "leaseSeconds", 60, "supportedGraphVersions", List.of("v3")));
        assertThat(claim.path("request").path("requestId")).isEqualTo(request.path("requestId"));
        var snapshot = (ObjectNode) mapper.readTree(getClass().getResourceAsStream("/v2/contracts.json")).get("general_answer").deepCopy();
        snapshot.put("implementationId", "v3").put("graphVersion", "v3").put("question", "인공 개념 질문");
        var body = Map.of("claimGeneration", claim.get("claimGeneration"), "requestRevision", claim.get("requestRevision"),
            "answer", Map.of("intent", "GENERAL_ANSWER", "status", "COMPLETE", "usedRunRefs", List.of(), "answerSnapshot", snapshot));
        String path = "/requests/" + request.path("requestId").asString() + "/finalize";
        snapshot.put("implementationId", "v2").put("graphVersion", "v2");
        assertThat(sendInternal(path, body).statusCode()).isEqualTo(400);
        snapshot.put("graphVersion", "v3");
        snapshot.put("implementationId", "v2");
        assertThat(sendInternal(path, body).statusCode()).isEqualTo(400);
        snapshot.put("implementationId", "v3");
        var completed = internal(path, body);
        assertThat(completed.path("status").asString()).isEqualTo("COMPLETED");
        assertThat(internal(path, body).path("turnId")).isEqualTo(completed.path("turnId"));
        assertThat(state().path("conversation").path("turns").get(0).path("answerSnapshot").path("graphVersion").asString()).isEqualTo("v3");
    }

    private JsonNode internal(String path, Object body) throws Exception {
        var response = sendInternal(path, body);
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);
        return json(response);
    }

    private HttpResponse<String> sendInternal(String path, Object body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/internal/agent" + path))
            .header("Content-Type", "application/json").header("X-Agent-Token", "synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        return HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
    }
}
