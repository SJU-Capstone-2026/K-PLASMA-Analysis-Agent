package com.kplasma.analysisagent.agent;

import java.io.IOException;
import java.net.InetAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.UUID;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** Local browser origin boundary. Worker routes retain their existing token authorization. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public final class LocalRuntimeAccessFilter extends OncePerRequestFilter {
    private final boolean enabled;
    private final String origin;
    private final String host;

    public LocalRuntimeAccessFilter(@Value("${AGENT_LOCAL_RUNTIME_ENABLED:false}") boolean enabled,
            @Value("${kplasma.agent.default-graph-version:v2}") String defaultGraphVersion,
            @Value("${kplasma.agent.supported-graph-versions:v2}") String supportedGraphVersions,
            @Value("${AGENT_LOCAL_UI_ORIGIN:}") String origin,
            @Value("${AGENT_LOCAL_API_HOST:}") String host) {
        this.enabled = enabled || "v2_localLLM".equals(defaultGraphVersion)
            || java.util.Arrays.stream(supportedGraphVersions.split(",")).anyMatch(v -> "v2_localLLM".equals(v.trim()));
        this.origin = origin;
        this.host = host;
        if (this.enabled && (!loopbackOrigin(origin)
                || !host.isEmpty() && !loopbackOrigin("http://" + host))) {
            throw new IllegalArgumentException("LOCAL_ACCESS_CONFIG_INVALID");
        }
    }

    private static boolean loopbackOrigin(String value) {
        try {
            var uri = URI.create(value);
            return "http".equals(uri.getScheme()) && uri.getPort() > 0 && uri.getPort() <= 65535
                && ("127.0.0.1".equals(uri.getHost()) || "[::1]".equals(uri.getHost()))
                && uri.getRawUserInfo() == null && uri.getRawQuery() == null && uri.getRawFragment() == null
                && (uri.getRawPath() == null || uri.getRawPath().isEmpty());
        } catch (IllegalArgumentException error) { return false; }
    }

    @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if (!enabled) { chain.doFilter(request, response); return; }
        response.setHeader("Cache-Control", "no-store");
        response.setHeader("Referrer-Policy", "no-referrer");
        response.setHeader("X-Content-Type-Options", "nosniff");
        String expectedHost = host.isEmpty() ? "127.0.0.1:" + request.getLocalPort() : host;
        if (!InetAddress.getByName(request.getRemoteAddr()).isLoopbackAddress()
                || !expectedHost.equals(request.getHeader("Host")) || Collections.list(request.getHeaders("Host")).size() != 1
                || Collections.list(request.getHeaders("Origin")).size() > 1
                || Collections.list(request.getHeaders("Sec-Fetch-Site")).size() > 1) {
            deny(response); return;
        }
        if ("/api/health".equals(request.getRequestURI())) { chain.doFilter(request, response); return; }
        String suppliedOrigin = request.getHeader("Origin");
        String site = request.getHeader("Sec-Fetch-Site");
        if ((suppliedOrigin != null && !origin.equals(suppliedOrigin))
                || (site != null && !site.equals("same-origin") && !site.equals("same-site"))) {
            deny(response); return;
        }
        if (request.getRequestURI().startsWith("/internal/agent/") && suppliedOrigin == null && site == null) {
            chain.doFilter(request, response); return;
        }
        if (suppliedOrigin == null && !"same-origin".equals(site)) { deny(response); return; }
        chain.doFilter(request, response);
    }

    private static void deny(HttpServletResponse response) throws IOException {
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json");
        response.getWriter().write("{\"code\":\"LOCAL_ACCESS_DENIED\",\"message\":\"설정된 로컬 앱 주소에서 다시 접속해 주세요.\","
            + "\"field\":null,\"details\":null,\"requestId\":\"" + UUID.randomUUID() + "\"}");
    }
}
