package com.kplasma.analysisagent.performance;

import com.kplasma.analysisagent.AnalysisAgentApplication;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import javax.sql.DataSource;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.*;
import org.springframework.http.*;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.ModelAndView;
import org.springframework.web.servlet.handler.AbstractHandlerExceptionResolver;
import tools.jackson.databind.ObjectMapper;

/** Explicit test-classpath entry point. Never packaged in the product JAR. */
public class ForwardLookupBenchmarkSupport {
    static final ThreadLocal<Stats> STATS = ThreadLocal.withInitial(Stats::new);
    static class Stats { int queries; long executeNanos; }

    public static void main(String[] args) {
        var app = new SpringApplication(AnalysisAgentApplication.class, Configuration.class);
        app.setAdditionalProfiles("forward-benchmark");
        // Command-line properties outrank service environment variables. No .env is read.
        app.run("--server.address=127.0.0.1", "--server.port=18085",
            "--spring.datasource.url=jdbc:postgresql://127.0.0.1:15445/forward_lookup_bench?prepareThreshold=0",
            "--spring.datasource.username=benchmark", "--spring.datasource.password=benchmark-local-only",
            "--spring.datasource.hikari.maximum-pool-size=2", "--spring.datasource.hikari.minimum-idle=2",
            "--kplasma.worker.enabled=false", "--kplasma.agent.worker-token=benchmark-local-only",
            "--kplasma.storage-root="+Path.of("../.local/performance/forward-lookup/storage").toAbsolutePath().normalize(),
            "--spring.jmx.enabled=false");
    }

    @TestConfiguration(proxyBeanMethods=false)
    @Profile("forward-benchmark")
    public static class Configuration {
        @Bean AbstractHandlerExceptionResolver benchmarkFailureDiagnostics() {
            var resolver = new AbstractHandlerExceptionResolver() {
                @Override protected ModelAndView doResolveException(HttpServletRequest req,
                        HttpServletResponse res, Object handler, Exception error) {
                    Throwable cause = error;
                    while (cause.getCause() != null) cause = cause.getCause();
                    String message = String.valueOf(cause.getMessage()).replace('\n', ' ');
                    System.out.printf("BENCH_ERROR %s %s %s%n", req.getRequestURI(),
                        cause.getClass().getSimpleName(), message.substring(0, Math.min(500, message.length())));
                    return null; // Preserve the real service's exception mapping and response.
                }
            };
            resolver.setOrder(Integer.MIN_VALUE);
            return resolver;
        }
        @Bean Endpoint benchmarkEndpoint(DataSource ds, ObjectMapper mapper) throws Exception {
            var jdbc = new NamedParameterJdbcTemplate(ds);
            if (!"forward_lookup_bench".equals(jdbc.queryForObject("select current_database()", Map.of(), String.class)))
                throw new IllegalStateException("Benchmark database required");
            return new Endpoint(jdbc, mapper);
        }
        @Bean OncePerRequestFilter benchmarkRequestMetrics() {
            return new OncePerRequestFilter() {
                @Override protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res,
                        FilterChain chain) throws ServletException, IOException {
                    STATS.set(new Stats()); long start = System.nanoTime();
                    try { chain.doFilter(req, res); }
                    finally {
                        var stats = STATS.get();
                        System.out.printf(Locale.ROOT,"BENCH_HTTP %s %s %d %d %.3f %.3f%n",
                            req.getMethod(), req.getRequestURI(), res.getStatus(), stats.queries,
                            stats.executeNanos/1e6, (System.nanoTime()-start)/1e6);
                        STATS.remove();
                    }
                }
            };
        }
        @Bean static BeanPostProcessor benchmarkJdbcMetrics() {
            return new BeanPostProcessor() {
                @Override public Object postProcessAfterInitialization(Object bean, String name) {
                    if (!(bean instanceof DataSource ds)) return bean;
                    return new DelegatingDataSource(ds) {
                        @Override public Connection getConnection() throws SQLException { return wrap(ds.getConnection()); }
                        @Override public Connection getConnection(String u,String p) throws SQLException { return wrap(ds.getConnection(u,p)); }
                    };
                }
            };
        }
    }

    static Object invoke(Method method, Object target, Object[] args) throws Throwable {
        try { return method.invoke(target, args); }
        catch (InvocationTargetException error) { throw error.getCause(); }
    }
    static Connection wrap(Connection connection) {
        return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(),new Class<?>[]{Connection.class},
            (proxy, method, args) -> {
                Object value = invoke(method, connection, args);
                if (!(value instanceof Statement stmt)) return value;
                Class<?> type = stmt instanceof CallableStatement ? CallableStatement.class
                    : stmt instanceof PreparedStatement ? PreparedStatement.class : Statement.class;
                return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (p,m,a) -> {
                    if (!m.getName().startsWith("execute")) return invoke(m,stmt,a);
                    var stats = STATS.get(); stats.queries++; long start = System.nanoTime();
                    try { return invoke(m,stmt,a); }
                    finally { stats.executeNanos += System.nanoTime()-start; }
                });
            });
    }

    @RestController
    @org.springframework.boot.test.context.TestComponent
    @Profile("forward-benchmark")
    public static class Endpoint {
        final NamedParameterJdbcTemplate jdbc;
        final ObjectMapper mapper;
        final Map<String,String> queries = new HashMap<>();
        Endpoint(NamedParameterJdbcTemplate jdbc, ObjectMapper mapper) throws IOException {
            this.jdbc=jdbc; this.mapper=mapper;
            for (String method : List.of("a","b","c"))
                queries.put(method,Files.readString(Path.of("../scripts/performance/forward-lookup/sql/"+method+".sql")));
        }
        @GetMapping("/benchmark/identity")
        public Map<String,Object> identity() {
            return Map.of("marker","forward-lookup-synthetic-only","database","forward_lookup_bench",
                "pid",ProcessHandle.current().pid(),"java",System.getProperty("java.version"),
                "maxHeapBytes",Runtime.getRuntime().maxMemory());
        }
        @GetMapping("/benchmark/lookup")
        public ResponseEntity<byte[]> lookup(@RequestParam String method, @RequestParam int pressure,
                @RequestParam int source, @RequestParam int bias) {
            if (!queries.containsKey(method) || pressure<0 || pressure>99 || source<0 || source>999 || bias<0 || bias>9999)
                return ResponseEntity.badRequest().build();
            long start=System.nanoTime(); long[] mapping={0};
            var runs=jdbc.query(queries.get(method),Map.of("pressure",pressure,"source",source,"bias",bias),(rs,n) -> {
                long begin=System.nanoTime();
                @SuppressWarnings("unchecked") Map<String,Object> row=mapper.readValue(rs.getString(1),Map.class);
                row.put("sourceFileCount",rs.getInt(2)); mapping[0]+=System.nanoTime()-begin; return row;
            });
            long fetched=System.nanoTime();
            byte[] body=mapper.writeValueAsBytes(Map.of("runs",runs));
            long serialized=System.nanoTime();
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON)
                .header("X-Bench-Queries",String.valueOf(STATS.get().queries))
                .header("X-Bench-Fetch-Ms",String.valueOf((fetched-start)/1e6))
                .header("X-Bench-Mapping-Ms",String.valueOf(mapping[0]/1e6))
                .header("X-Bench-Serialize-Ms",String.valueOf((serialized-fetched)/1e6))
                .body(body);
        }
    }
}
