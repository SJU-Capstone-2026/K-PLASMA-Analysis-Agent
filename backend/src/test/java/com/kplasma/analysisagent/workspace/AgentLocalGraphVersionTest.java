package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.HttpCookie;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@TestPropertySource(properties={"kplasma.agent.worker-token=synthetic-worker-token",
    "kplasma.agent.supported-graph-versions=v2_localLLM", "kplasma.agent.default-graph-version=v2_localLLM",
    "AGENT_LOCAL_RUNTIME_ENABLED=false", "AGENT_LOCAL_UI_ORIGIN=http://127.0.0.1:5173",
    "AGENT_LOCAL_API_HOST=", "AGENT_LOCAL_BOOTSTRAP_TOKEN=synthetic-local-bootstrap-token"})
class AgentLocalGraphVersionTest extends WorkspaceTestSupport {
    private String sessionCookie;

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

    @Override protected HttpResponse<String> send(String method, String path, Object body, String key) throws Exception {
        if (sessionCookie == null) {
            var response = exchange(browserRequest("POST", "/api/local-runtime/session", null, null)
                .header("X-Local-Bootstrap", "synthetic-local-bootstrap-token"));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(204);
            String header = response.headers().firstValue("Set-Cookie").orElseThrow();
            assertThat(header).contains("HttpOnly", "SameSite=Strict");
            var cookie = HttpCookie.parse(header).getFirst();
            sessionCookie = cookie.getName() + "=" + cookie.getValue();
        }
        return exchange(browserRequest(method, path, body, key).header("Cookie", sessionCookie));
    }

    private void assertSessionBoundary() throws Exception {
        for (String path : List.of("/api/workspace", "/api/agent/requests/artificial/events")) {
            var response = exchange(browserRequest("GET", path, null, null)
                .header("Accept", path.endsWith("/events") ? "text/event-stream" : "application/json"));
            assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(401);
            assertThat(json(response).path("code").asString()).isEqualTo("LOCAL_ACCESS_DENIED");
        }
        var crossSite = exchange(browserRequest("GET", "/api/workspace", null, null)
            .header("Cookie", sessionCookie).setHeader("Origin", "https://outside.invalid")
            .setHeader("Sec-Fetch-Site", "cross-site"));
        assertThat(crossSite.statusCode()).isEqualTo(403);
    }

    @Test void localIntakeDefaultsToItsOwnVersionAndRejectsCloudBeforeEnqueue() throws Exception {
        assertSessionBoundary();
        for (String version : List.of("v1", "v2", "v3")) {
            var rejected = send("POST", "/api/agent/requests",
                Map.of("text", "실행하지 않을 인공 질문", "stateToken", token(), "graphVersion", version), "reject-" + version);
            assertThat(rejected.statusCode()).isEqualTo(400);
        }
        assertThat(jdbc.queryForObject("select count(*) from agent_request where status='QUEUED'", Integer.class)).isZero();
        var request = ok("POST", "/api/agent/requests", Map.of("text", "로컬 인공 질문", "stateToken", token()), "local-default");
        assertThat(request.path("graphVersion").asString()).isEqualTo("v2_localLLM");
        assertThat(state().path("conversation").path("agentGraphVersion").asString()).isEqualTo("v2_localLLM");
    }
}
