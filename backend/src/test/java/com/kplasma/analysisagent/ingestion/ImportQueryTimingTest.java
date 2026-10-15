package com.kplasma.analysisagent.ingestion;

import com.zaxxer.hikari.*;
import java.nio.file.*;
import java.sql.SQLException;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.*;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.*;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
class ImportQueryTimingTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    @TempDir Path temp;
    final ObjectMapper mapper=new ObjectMapper();
    List<JsonNode> events(Path log)throws Exception{return Files.readAllLines(log).stream().map(mapper::readTree).toList();}
    @Test void tracesLookupStatusAndValidatedCorrelationWithoutChangingResponse()throws Exception {
        Path log=temp.resolve("query.jsonl");
        try(var recorder=new ImportTimingRecorder(log,System::nanoTime)){
            var filter=new ImportTimingFilter(recorder);
            var request=new MockHttpServletRequest("GET","/api/run-versions/not-a-uuid");
            request.addHeader("X-Benchmark-Request-Id","trial-1-lookup-2");
            var response=new MockHttpServletResponse();
            filter.doFilter(request,response,(req,res)->{res.setContentType("application/json");((jakarta.servlet.http.HttpServletResponse)res).setStatus(400);res.getWriter().write("{\"error\":\"INVALID_IDENTIFIER\"}");});
            assertThat(response.getContentAsString()).isEqualTo("{\"error\":\"INVALID_IDENTIFIER\"}");
        }
        var root=events(log).getLast();
        assertThat(root.path("kind").asString()).isEqualTo("lookup");
        assertThat(root.path("id").asString()).isEqualTo("trial-1-lookup-2");
        assertThat(root.path("status").asInt()).isEqualTo(400);
    }
    @Test void invalidCorrelationIsNotLoggedAndUnknownPathsAreIgnored()throws Exception {
        Path log=temp.resolve("filtered.jsonl");
        try(var recorder=new ImportTimingRecorder(log,System::nanoTime)){
            var filter=new ImportTimingFilter(recorder);
            var request=new MockHttpServletRequest("GET","/api/run-versions/missing");
            request.addHeader("X-Benchmark-Request-Id","bad identifier / sensitive");
            filter.doFilter(request,new MockHttpServletResponse(),(req,res)->((jakarta.servlet.http.HttpServletResponse)res).setStatus(404));
            filter.doFilter(new MockHttpServletRequest("GET","/unrelated"),new MockHttpServletResponse(),(req,res)->{});
        }
        assertThat(events(log)).hasSize(1);
        assertThat(Files.readString(log)).doesNotContain("bad identifier","sensitive","/unrelated");
        assertThat(events(log).getFirst().path("status").asInt()).isEqualTo(404);
    }
    @Test void realPoolWaitAndTimeoutAreTracedWithoutInventingHeldConnection()throws Exception {
        var config=new HikariConfig();config.setJdbcUrl(DB.getJdbcUrl());config.setUsername(DB.getUsername());config.setPassword(DB.getPassword());
        config.setMaximumPoolSize(1);config.setMinimumIdle(1);config.setConnectionTimeout(250);
        Path log=temp.resolve("pool.jsonl");
        try(var pool=new HikariDataSource(config);var recorder=new ImportTimingRecorder(log,System::nanoTime);var executor=Executors.newSingleThreadExecutor()){
            var timed=ImportSqlTimingConfiguration.timed(pool,recorder);
            try(var held=pool.getConnection()){
                var started=new CountDownLatch(1);
                var future=executor.submit(()->{try(var trace=recorder.begin("lookup","timeout")){started.countDown();assertThatThrownBy(timed::getConnection).isInstanceOf(SQLException.class);}return null;});
                assertThat(started.await(5,TimeUnit.SECONDS)).isTrue();future.get(5,TimeUnit.SECONDS);
            }
            try(var trace=recorder.begin("lookup","ok");var connection=timed.getConnection();var statement=connection.createStatement();var rows=statement.executeQuery("select 7")){
                assertThat(rows.next()).isTrue();assertThat(rows.getInt(1)).isEqualTo(7);
            }
            assertThat(pool.getHikariPoolMXBean().getActiveConnections()).isZero();
        }
        var all=events(log);var failed=all.stream().filter(e->e.path("id").asString().equals("timeout")).toList();
        assertThat(failed.stream().filter(e->e.path("phase").asString().equals("db.connection_held"))).isEmpty();
        var acquire=failed.stream().filter(e->e.path("phase").asString().equals("db.acquire")).findFirst().orElseThrow();
        assertThat(acquire.path("outcome").asString()).isEqualTo("error");
        assertThat(acquire.path("endNs").asLong()-acquire.path("startNs").asLong()).isPositive();
        assertThat(all.stream().filter(e->e.path("phase").asString().equals("db.execute"))).hasSize(1);
    }
    @Test void concurrentRequestContextsStaySeparateAndDisabledRecordingIsNoop()throws Exception {
        Path log=temp.resolve("parallel.jsonl");
        try(var recorder=new ImportTimingRecorder(log,System::nanoTime);var executor=Executors.newFixedThreadPool(2)){
            var barrier=new CyclicBarrier(2);var futures=new ArrayList<Future<?>>();
            for(String id:List.of("one","two"))futures.add(executor.submit(()->{try(var trace=recorder.begin("lookup",id)){barrier.await(5,TimeUnit.SECONDS);try(var span=recorder.measure("db.acquire")){span.field("owner",id);}}catch(Exception e){throw new RuntimeException(e);}}));
            for(var f:futures)f.get(5,TimeUnit.SECONDS);
        }
        for(var event:events(log))if(event.has("owner"))assertThat(event.get("owner")).isEqualTo(event.get("id"));
        try(var off=new ImportTimingRecorder(null,System::nanoTime)){
            var request=new MockHttpServletRequest("GET","/api/run-versions/x");
            new ImportTimingFilter(off).doFilter(request,new MockHttpServletResponse(),(req,res)->res.getWriter().write("same"));
        }
        assertThat(Files.list(temp).count()).isEqualTo(1);
    }
}
