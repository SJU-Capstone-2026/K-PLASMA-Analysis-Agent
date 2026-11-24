package com.kplasma.analysisagent.agent;

import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class LocalRuntimeAccessTest {
    @Test void accessErrorsPreserveTheExistingErrorEnvelopeAndRequestIdentity() throws Exception {
        var request = request("GET", "/api/workspace");
        request.removeHeader("Sec-Fetch-Site");
        request.addHeader("Sec-Fetch-Site", "cross-site");
        var response = run(filter(), request);
        assertThat(response.getStatus()).isEqualTo(403);
        var body = tools.jackson.databind.json.JsonMapper.builder().build().readTree(response.getContentAsString());
        assertThat(body.path("code").asString()).isEqualTo("LOCAL_ACCESS_DENIED");
        assertThat(body.path("requestId").asString()).matches("[a-f0-9-]{36}");
        assertThat(body.has("field")).isTrue();
        assertThat(body.has("details")).isTrue();
    }

    @Test void anonymousReadinessCanReachOnlyTheFixedHealthEndpoint() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/health");
        request.addHeader("Host", "127.0.0.1:8080");
        var response = new MockHttpServletResponse();
        filter().doFilter(request, response, (req, res) -> res.getWriter().write("UP"));
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(response.getContentAsString()).isEqualTo("UP");
        request = new MockHttpServletRequest("GET", "/api/health/../workspace");
        request.addHeader("Host", "127.0.0.1:8080");
        assertThat(run(filter(), request).getStatus()).isEqualTo(403);
    }

    private LocalRuntimeAccessFilter filter() {
        return new LocalRuntimeAccessFilter(true, "v2", "v2", "http://127.0.0.1:5173", "127.0.0.1:8080");
    }

    private MockHttpServletRequest request(String method, String path) {
        var request = new MockHttpServletRequest(method, path);
        request.addHeader("Host", "127.0.0.1:8080");
        request.addHeader("Origin", "http://127.0.0.1:5173");
        request.addHeader("Sec-Fetch-Site", "same-site");
        return request;
    }

    private MockHttpServletResponse run(LocalRuntimeAccessFilter filter, MockHttpServletRequest request) throws Exception {
        var response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> res.getWriter().write("synthetic-data"));
        return response;
    }

    @Test void servesTrustedBrowserWithoutSessionAcrossReadsAndMutations() throws Exception {
        var filter = filter();
        for (String path : new String[]{"/api/workspace", "/api/runs/file", "/api/agent/requests/id/events"}) {
            var response = run(filter, request("GET", path));
            assertThat(response.getStatus()).isEqualTo(200);
            assertThat(response.getContentAsString()).isEqualTo("synthetic-data");
            assertThat(response.getCookies()).isEmpty();
        }
        assertThat(run(filter, request("POST", "/api/workspace/reset")).getStatus()).isEqualTo(200);
    }

    @Test void acceptsSameOriginReadsWithoutAnOriginHeader() throws Exception {
        var filter = filter();
        var read = request("GET", "/api/agent/requests/id/events");
        read.removeHeader("Origin");
        assertThat(run(filter, read).getStatus()).isEqualTo(403);
        read.removeHeader("Sec-Fetch-Site");
        assertThat(run(filter, read).getStatus()).isEqualTo(403);
        read.addHeader("Sec-Fetch-Site", "same-origin");
        assertThat(run(filter, read).getContentAsString()).isEqualTo("synthetic-data");
    }

    @Test void rejectsRebindingCrossOriginAndNonLoopbackRequests() throws Exception {
        var filter = filter();
        for (String origin : new String[]{"https://outside.invalid", "null", "http://127.0.0.1:5174"}) {
            var read = request("GET", "/api/workspace");
            read.removeHeader("Origin");
            read.addHeader("Origin", origin);
            assertThat(run(filter, read).getStatus()).isEqualTo(403);
        }
        var read = request("GET", "/api/workspace");
        read.addHeader("Origin", "http://127.0.0.1:5173");
        assertThat(run(filter, read).getStatus()).isEqualTo(403);
        read = request("GET", "/api/workspace");
        read.removeHeader("Host");
        read.addHeader("Host", "rebind.invalid:8080");
        assertThat(run(filter, read).getStatus()).isEqualTo(403);
        read = request("GET", "/api/workspace");
        read.setRemoteAddr("192.0.2.1");
        assertThat(run(filter, read).getStatus()).isEqualTo(403);
    }

    @Test void internalWorkerStillReachesItsExistingTokenAuthorization() throws Exception {
        var request = request("POST", "/internal/agent/claim");
        request.removeHeader("Origin");
        request.removeHeader("Sec-Fetch-Site");
        assertThat(run(filter(), request).getContentAsString()).isEqualTo("synthetic-data");
    }

    @Test void disabledFilterPreservesCloudBehavior() throws Exception {
        var filter = new LocalRuntimeAccessFilter(false, "v2", "v2", "", "");
        var invoked = new AtomicBoolean();
        filter.doFilter(new MockHttpServletRequest("GET", "/api/workspace"), new MockHttpServletResponse(),
            (request, response) -> invoked.set(true));
        assertThat(invoked).isTrue();
    }

    @Test void localDefaultRequiresValidOriginConfigurationEvenWhenFlagIsFalse() {
        for (String origin : new String[]{"", "http://localhost:5173", "http://127.0.0.1:70000"}) {
            assertThatThrownBy(() -> new LocalRuntimeAccessFilter(false, "v2_localLLM", "v2_localLLM", origin, ""))
                .isInstanceOf(IllegalArgumentException.class).hasMessage("LOCAL_ACCESS_CONFIG_INVALID");
        }
        assertThatThrownBy(() -> new LocalRuntimeAccessFilter(false, "v2_localLLM", "v2_localLLM", "http://127.0.0.1:5173", "localhost:8080"))
            .isInstanceOf(IllegalArgumentException.class).hasMessage("LOCAL_ACCESS_CONFIG_INVALID");
    }

    @Test void derivesAnUnconfiguredHostFromTheServerPortAndRejectsRequestAuthoritySubstitutes() throws Exception {
        var filter = new LocalRuntimeAccessFilter(false, "v2_localLLM", "v2_localLLM", "http://127.0.0.1:5173", "");
        var read = request("GET", "/api/workspace");
        read.setLocalPort(43123);
        read.removeHeader("Host");
        read.addHeader("Host", "127.0.0.1:43123");
        assertThat(run(filter, read).getContentAsString()).isEqualTo("synthetic-data");
        for (String host : new String[]{"127.0.0.1:8080", "localhost:43123", "rebind.invalid:43123"}) {
            read.removeHeader("Host");
            read.addHeader("Host", host);
            read.addHeader("X-Forwarded-Host", "127.0.0.1:43123");
            assertThat(run(filter, read).getStatus()).isEqualTo(403);
        }
    }
}
