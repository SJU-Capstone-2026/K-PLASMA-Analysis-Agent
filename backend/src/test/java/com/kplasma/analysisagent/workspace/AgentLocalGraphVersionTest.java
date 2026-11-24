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

@TestPropertySource(properties={"kplasma.agent.worker-token=synthetic-worker-token",
    "kplasma.agent.supported-graph-versions=v2_localLLM", "kplasma.agent.default-graph-version=v2_localLLM",
    "AGENT_LOCAL_RUNTIME_ENABLED=false", "AGENT_LOCAL_UI_ORIGIN=http://127.0.0.1:5173",
    "AGENT_LOCAL_API_HOST="})
class AgentLocalGraphVersionTest extends WorkspaceTestSupport {

    private HttpRequest.Builder browserRequest(String method, String path, Object body, String key) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
            .header("Content-Type", "application/json")
            .header("Origin", "http://127.0.0.1:5173").header("Sec-Fetch-Site", "same-site");
        if (key != null) request.header("Idempotency-Key", key);
        return request.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
    }

    private HttpResponse<String> exchange(HttpRequest.Builder request) throws Exception {
        return HttpClient.newHttpClient().send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest.Builder workerRequest(String path, Object body) throws Exception {
        return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/internal/agent" + path))
            .header("Content-Type", "application/json").header("X-Agent-Token", "synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
    }

    @Override protected HttpResponse<String> send(String method, String path, Object body, String key) throws Exception {
        return exchange(browserRequest(method, path, body, key));
    }

    private void assertLocalBoundary() throws Exception {
        for (String path : List.of("/api/workspace", "/api/agent/requests/artificial/events")) {
            var response = exchange(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .header("Accept", path.endsWith("/events") ? "text/event-stream" : "application/json"));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(403);
            assertThat(json(response).path("code").asString()).isEqualTo("LOCAL_ACCESS_DENIED");
        }
        var crossSite = exchange(browserRequest("GET", "/api/workspace", null, null)
            .setHeader("Origin", "https://outside.invalid")
            .setHeader("Sec-Fetch-Site", "cross-site"));
        assertThat(crossSite.statusCode()).isEqualTo(403);
    }

    @Test void localIntakeDefaultsToItsOwnVersionAndRejectsCloudBeforeEnqueue() throws Exception {
        assertLocalBoundary();
        var beforeDemo = token();
        rejects("POST", "/api/workspace/new-conversation", Map.of("stateToken", beforeDemo, "decisionDemo", true),
            null, 400, "INVALID_AGENT_REQUEST");
        assertThat(token()).isEqualTo(beforeDemo);
        for (String version : List.of("v1", "v2")) {
            var rejected = send("POST", "/api/agent/requests",
                Map.of("text", "실행하지 않을 인공 질문", "stateToken", token(), "graphVersion", version), "reject-" + version);
            assertThat(rejected.statusCode()).isEqualTo(400);
        }
        assertThat(jdbc.queryForObject("select count(*) from agent_request where status='QUEUED'", Integer.class)).isZero();
        var request = ok("POST", "/api/agent/requests", Map.of("text", "로컬 인공 질문", "stateToken", token()), "local-default");
        assertThat(request.path("graphVersion").asString()).isEqualTo("v2_localLLM");
        assertThat(state().path("conversation").path("agentGraphVersion").asString()).isEqualTo("v2_localLLM");
        assertPlanJournalKeepsOriginalJson(request.path("requestId").asString());
    }

    private void assertLocalQwenPlanDeadlines(String requestId, JsonNode claim) throws Exception {
        String path = "/requests/" + requestId + "/model-attempts";
        for (var role : Map.of("PLAN_INITIAL", 120, "REPLAN", 120, "PLAN_REVIEW", 90, "COMPOSE", 90).entrySet()) {
            var before = jdbc.queryForObject("select clock_timestamp()", java.sql.Timestamp.class).toInstant();
            var response = exchange(workerRequest(path, Map.of("claimGeneration", claim.path("claimGeneration"),
                "requestRevision", claim.path("requestRevision"), "kind", role.getKey(), "key", role.getKey())));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);
            var after = jdbc.queryForObject("select clock_timestamp()", java.sql.Timestamp.class).toInstant();
            var deadline = jdbc.queryForObject("select deadline from agent_v2_model_attempt where id=?::uuid",
                java.sql.Timestamp.class, json(response).path("attemptId").asString()).toInstant();
            assertThat(deadline).isBetween(before.plusSeconds(role.getValue()), after.plusSeconds(role.getValue()));
        }
    }

    private void assertPlanJournalKeepsOriginalJson(String requestId) throws Exception {
        var claimed = exchange(workerRequest("/claim", Map.of(
            "workerId", "synthetic-local-worker", "leaseSeconds", 60,
            "supportedGraphVersions", List.of("v2_localLLM"))));
        assertThat(claimed.statusCode()).describedAs(claimed.body()).isEqualTo(200);
        var claim = json(claimed);
        assertLocalQwenPlanDeadlines(requestId, claim);
        int revision = 0;
        for (String field : List.of("requires", "required_prior_outputs")) {
            var plan = mapper.readTree("""
                {"schema_version":2,"request_mode":"general_only","base_revision":%s,
                 "requirements":[{"id":"r1","text":"인공 개념 질문",
                  "sources":[{"message_key":"question","quote":"인공 개념 질문"}],"handled_by":["explain"]}],
                 "steps":[{"id":"explain","kind":"tool","tool":"explain_answer",
                  "requirement_ids":["r1"],"depends_on":[],"%s":[],"run_if":[],"inputs":{"mode":"concept"}}]}
                """.formatted(revision == 0 ? "null" : revision, field));
            var response = exchange(workerRequest("/requests/" + requestId + "/plans",
                Map.of("claimGeneration", claim.path("claimGeneration"), "requestRevision", claim.path("requestRevision"),
                    "payload", plan)));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);
            assertThat(json(response).path("revision").asInt()).isEqualTo(++revision);
            assertThat(json(response).path("plan")).isEqualTo(plan);
        }
        var plans = jdbc.queryForList(
            "select plan::text from agent_v2_plan_revision where request_id=?::uuid order by revision", String.class, requestId);
        assertThat(plans).hasSize(2);
        assertThat(mapper.readTree(plans.getFirst()).path("steps").get(0).has("requires")).isTrue();
        assertThat(mapper.readTree(plans.getFirst()).path("steps").get(0).has("required_prior_outputs")).isFalse();
        assertThat(mapper.readTree(plans.getLast()).path("steps").get(0).has("required_prior_outputs")).isTrue();
    }
}
