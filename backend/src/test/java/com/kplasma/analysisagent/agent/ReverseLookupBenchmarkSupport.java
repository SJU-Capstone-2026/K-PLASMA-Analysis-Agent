package com.kplasma.analysisagent.agent;

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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.ModelAndView;
import org.springframework.web.servlet.handler.AbstractHandlerExceptionResolver;
import tools.jackson.databind.ObjectMapper;

/** Explicit test-classpath entry point. Never packaged in the product JAR. */
public class ReverseLookupBenchmarkSupport {
    static final ThreadLocal<Stats> STATS = ThreadLocal.withInitial(Stats::new);
    static class Stats { int queries; long executeNanos; }

    public static void main(String[] args) {
        if (Arrays.equals(args,new String[]{"--dump-query-sql"})) {
            var query=new ReverseContextQuery(Map.of("constraints",List.of(Map.of("metric","meanIonEnergy","operator","between","min",150,"max",160,"unit","eV")),"goals",List.of(Map.of("metric","ionFlux","direction","maximize","unit","10¹⁸ m⁻²s⁻¹"))));
            var sql=query.select();String text=sql.text();
            for(Object value:sql.arguments())text=text.replaceFirst("\\?",String.valueOf(value));
            System.out.println(text+";");return;
        }
        var app = new SpringApplication(AnalysisAgentApplication.class, Configuration.class);
        app.setAdditionalProfiles("reverse-benchmark");
        // Command-line properties outrank service environment variables. No .env is read.
        app.run("--server.address=127.0.0.1", "--server.port=18088",
            "--spring.datasource.url=jdbc:postgresql://127.0.0.1:15448/reverse_lookup_bench?prepareThreshold=0",
            "--spring.datasource.username=benchmark", "--spring.datasource.password=benchmark-local-only",
            "--spring.datasource.hikari.maximum-pool-size=2", "--spring.datasource.hikari.minimum-idle=2",
            "--kplasma.worker.enabled=false", "--kplasma.agent.worker-token=benchmark-local-only",
            "--kplasma.storage-root="+Path.of("../.local/performance/reverse-lookup/storage").toAbsolutePath().normalize(),
            "--spring.jmx.enabled=false", "--spring.flyway.target="+System.getProperty("benchmark.flyway-target","7"));
    }

    @TestConfiguration(proxyBeanMethods=false)
    @Profile("reverse-benchmark")
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
            var jdbc = new JdbcTemplate(ds);
            if (!"reverse_lookup_bench".equals(jdbc.queryForObject("select current_database()", String.class)))
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
    @Profile("reverse-benchmark")
    public static class Endpoint {
        final JdbcTemplate jdbc;
        final ObjectMapper mapper;
        Endpoint(JdbcTemplate jdbc, ObjectMapper mapper) {this.jdbc=jdbc; this.mapper=mapper;}
        @GetMapping("/benchmark/identity")
        public Map<String,Object> identity() {
            return Map.of("marker","reverse-lookup-synthetic-only","database","reverse_lookup_bench",
                "pid",ProcessHandle.current().pid(),"java",System.getProperty("java.version"),
                "maxHeapBytes",Runtime.getRuntime().maxMemory());
        }
        @PostMapping("/benchmark/query")
        public ResponseEntity<byte[]> query(@RequestBody Map<String,Object> input) throws Exception {
            long start=System.nanoTime();
            var query=new ReverseContextQuery(input);
            var select=Arrays.stream(ReverseContextQuery.class.getDeclaredMethods()).filter(m->m.getName().equals("select")).findFirst().orElseThrow();
            String[] pinned=select.getParameterCount()==0?new String[0]:jdbc.queryForList("select current_version_id::text from run where current_version_id is not null order by run_id",String.class).toArray(String[]::new);
            var sql=(ReverseContextQuery.Sql)(select.getParameterCount()==0?select.invoke(query):select.invoke(query,(Object)pinned));
            long before=System.nanoTime();
            var runs=jdbc.query(sql.text(),(rs,n)->{var row=mapper.readValue(rs.getString(1),Map.class);row.put("sourceFileCount",rs.getObject(2));return row;},sql.arguments().toArray());
            long fetched=System.nanoTime();
            byte[] body=mapper.writeValueAsBytes(Map.of("runs",runs));
            long serialized=System.nanoTime();
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON)
                .header("X-Bench-Queries",String.valueOf(STATS.get().queries))
                .header("X-Bench-Db-Ms",String.valueOf(STATS.get().executeNanos/1e6))
                .header("X-Bench-Fetch-Ms",String.valueOf((fetched-before)/1e6))
                .header("X-Bench-Inventory-Ms",String.valueOf((before-start)/1e6))
                .header("X-Bench-Catalog-Refs",String.valueOf(pinned.length))
                .header("X-Bench-Serialize-Ms",String.valueOf((serialized-fetched)/1e6)).body(body);
        }
        @PostMapping("/benchmark/explain")
        public Object explain(@RequestBody Map<String,Object> input) throws Exception {
            var query=new ReverseContextQuery(input);
            var select=Arrays.stream(ReverseContextQuery.class.getDeclaredMethods()).filter(m->m.getName().equals("select")).findFirst().orElseThrow();
            String[] pinned=select.getParameterCount()==0?new String[0]:jdbc.queryForList("select current_version_id::text from run where current_version_id is not null order by run_id",String.class).toArray(String[]::new);
            var sql=(ReverseContextQuery.Sql)(select.getParameterCount()==0?select.invoke(query):select.invoke(query,(Object)pinned));
            return mapper.readTree(jdbc.queryForObject("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) "+sql.text(),String.class,sql.arguments().toArray()));
        }
    }
}
