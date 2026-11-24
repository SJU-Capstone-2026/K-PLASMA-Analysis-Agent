package com.kplasma.analysisagent.agent;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** Local browser session boundary. Worker routes retain their existing token authorization. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public final class LocalRuntimeAccessFilter extends OncePerRequestFilter {
    private static final String COOKIE = "KPLASMA_LOCAL_SESSION";
    private final boolean enabled;
    private final String origin;
    private final String host;
    private final byte[] bootstrap;
    private final AtomicBoolean consumed = new AtomicBoolean();
    private volatile byte[] session;
    private volatile Instant expires = Instant.EPOCH;

    public LocalRuntimeAccessFilter(@Value("${AGENT_LOCAL_RUNTIME_ENABLED:false}") boolean enabled,
            @Value("${kplasma.agent.default-graph-version:v2}") String defaultGraphVersion,
            @Value("${kplasma.agent.supported-graph-versions:v2}") String supportedGraphVersions,
            @Value("${AGENT_LOCAL_UI_ORIGIN:}") String origin,
            @Value("${AGENT_LOCAL_API_HOST:}") String host,
            @Value("${AGENT_LOCAL_BOOTSTRAP_TOKEN:}") String bootstrap) {
        this.enabled = enabled || "v2_localLLM".equals(defaultGraphVersion)
            || java.util.Arrays.stream(supportedGraphVersions.split(",")).anyMatch(v -> "v2_localLLM".equals(v.trim()));
        this.origin = origin;
        this.host = host;
        this.bootstrap = hash(bootstrap);
        if (this.enabled && (!loopbackOrigin(origin)
                || !host.isEmpty() && !loopbackOrigin("http://" + host) || bootstrap.length() < 16)) {
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
        if (!expectedHost.equals(request.getHeader("Host")) || Collections.list(request.getHeaders("Host")).size() != 1
                || Collections.list(request.getHeaders("Origin")).size() > 1
                || Collections.list(request.getHeaders("Sec-Fetch-Site")).size() > 1) {
            deny(response, 403); return;
        }
        if ("/api/health".equals(request.getRequestURI())) { chain.doFilter(request, response); return; }
        String suppliedOrigin = request.getHeader("Origin");
        String site = request.getHeader("Sec-Fetch-Site");
        if ((suppliedOrigin != null && !origin.equals(suppliedOrigin))
                || (site != null && !site.equals("same-origin") && !site.equals("same-site"))) {
            deny(response, 403); return;
        }
        if (request.getRequestURI().startsWith("/internal/agent/") && suppliedOrigin == null && site == null) {
            chain.doFilter(request, response); return;
        }
        if (suppliedOrigin == null && site == null) { deny(response, 403); return; }
        if ("/api/local-runtime/session".equals(request.getRequestURI())) {
            String token = request.getHeader("X-Local-Bootstrap");
            if (!"POST".equals(request.getMethod()) || token == null
                    || !MessageDigest.isEqual(bootstrap, hash(token)) || !consumed.compareAndSet(false, true)) {
                deny(response, 401); return;
            }
            byte[] random = new byte[32];
            new SecureRandom().nextBytes(random);
            String value = Base64.getUrlEncoder().withoutPadding().encodeToString(random);
            session = hash(value);
            expires = Instant.now().plusSeconds(8 * 60 * 60);
            var cookie = new Cookie(COOKIE, value);
            cookie.setHttpOnly(true);
            cookie.setAttribute("SameSite", "Strict");
            cookie.setPath("/api");
            cookie.setMaxAge(8 * 60 * 60);
            response.addCookie(cookie);
            response.setStatus(204);
            return;
        }
        byte[] expected = session;
        if (expected != null && Instant.now().isBefore(expires) && request.getCookies() != null) {
            for (var cookie : request.getCookies()) {
                if (COOKIE.equals(cookie.getName()) && MessageDigest.isEqual(expected, hash(cookie.getValue()))) {
                    chain.doFilter(request, response); return;
                }
            }
        }
        deny(response, 401);
    }

    private static byte[] hash(String value) {
        try { return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)); }
        catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    private static void deny(HttpServletResponse response, int status) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.getWriter().write("{\"code\":\"LOCAL_ACCESS_DENIED\",\"message\":\"로컬 연결 인증이 필요합니다.\","
            + "\"field\":null,\"details\":null,\"requestId\":\"" + UUID.randomUUID() + "\"}");
    }
}
