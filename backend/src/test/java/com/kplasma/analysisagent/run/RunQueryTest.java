package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.*;
import com.kplasma.analysisagent.ingestion.*;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="kplasma.worker.enabled=false")
@Import(RunQueryTest.Time.class)
class RunQueryTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp();
    @TestConfiguration static class Time { @Bean @Primary Clock fixedClock() { return Clock.fixed(Instant.parse("2026-01-02T03:04:05Z"),ZoneOffset.UTC); } }
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) { r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString); }
    @Autowired ImportIntakeService intake; @Autowired SourceStore store; @Autowired ImportWorker worker;
    @Autowired RunQueryService query; @Autowired ObjectMapper mapper; @Autowired JdbcTemplate jdbc; @LocalServerPort int port;
    @BeforeEach void clear() { jdbc.execute("truncate import_batch, source_set, run cascade"); }
    ImportDto.BatchView accept(boolean complete) throws Exception {
        Map<String,String> files=new HashMap<>(SyntheticRunFiles.files(UUID.randomUUID().toString()));
        if(!complete) files.remove("0d_result/log/output.log"); files.put("notes.txt","ancillary original");
        List<ImportDto.UploadEntry> entries=new ArrayList<>();List<UploadPart> parts=new ArrayList<>();
        for(var e:files.entrySet()) { String name="f"+entries.size(); Path p=Files.createTempFile(ROOT,"part-",".txt");Files.writeString(p,e.getValue());entries.add(new ImportDto.UploadEntry(name,"wrapped/run/"+e.getKey()));parts.add(new UploadPart(name,p,Files.size(p))); }
        var batch=intake.accept(store.stage(new ImportDto.UploadManifest("FOLDER",entries),parts),UUID.randomUUID().toString());
        worker.process(UUID.fromString(batch.jobs().getFirst().jobId())); return intake.get(batch.batchId());
    }
    HttpResponse<String> get(String path) throws Exception { return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+path)).GET().build(),HttpResponse.BodyHandlers.ofString()); }
    @Test void publishesFullVersionAndSummaryWithFrozenRegistrationAndDistinctPresentationAndManifest() throws Exception {
        var batch=accept(true); String job=batch.jobs().getFirst().jobId(),version=batch.jobs().getFirst().runVersionId();
        var summaries=get("/api/runs"); assertThat(summaries.statusCode()).isEqualTo(200);
        var summary=mapper.readTree(summaries.body()).get(0); assertThat(summary.get("registeredAt").stringValue()).isEqualTo("2026-01-02T03:04:05Z");
        assertThat(summary.has("iedDistribution")).isFalse(); assertThat(summary.get("qualityStatus").stringValue()).isEqualTo("VERIFIED");
        var full=get("/api/run-versions/"+version); assertThat(full.statusCode()).isEqualTo(200);
        var f=mapper.readTree(full.body()); assertThat(f.get("sourceFiles").size()).isEqualTo(3);
        assertThat(f.get("sourceFiles").get(0).get("path").stringValue()).isEqualTo("PRS_02/Source_100/Bias_0000/0d_setting.ini");
        assertThat(f.get("analysis").get("strictConvergence").booleanValue()).isFalse(); assertThat(f.get("metrics").get("iedWidth").isNull()).isTrue();
        var manifest=get("/api/import-jobs/"+job+"/files"); assertThat(manifest.statusCode()).isEqualTo(200);
        var m=mapper.readTree(manifest.body());assertThat(m.size()).isEqualTo(5); assertThat(manifest.body()).contains("wrapped/run/notes.txt","wrapped/run/0d_result/log/output.log").doesNotContain(ROOT.toString(),"storage_path");
    }
    @Test void catalogFiltersRunsAndFailuresWithoutPublishingFailuresIntoSearch() throws Exception {
        accept(true);accept(false);
        var catalog=get("/api/catalog?status=INCOMPLETE"); var tree=mapper.readTree(catalog.body());
        assertThat(tree.get("runs").size()).isZero();assertThat(tree.get("jobs").size()).isEqualTo(1);
        assertThat(mapper.readTree(get("/api/catalog?quality=VERIFIED").body()).get("runs").size()).isEqualTo(1);
        assertThat(mapper.readTree(get("/api/catalog?search=RUN-P02").body()).get("runs").size()).isEqualTo(1);
        assertThat(mapper.readTree(get("/api/catalog?search=absent").body()).get("runs").size()).isZero();
        assertThat(query.listSearchable()).hasSize(1);
        var all=mapper.readTree(get("/api/catalog").body());
        String version=all.get("runs").get(0).get("runVersionId").stringValue();
        assertThat(all.get("sourceFilesByVersion").get(version).size()).isEqualTo(3);
        assertThat(mapper.readTree(get("/api/catalog?search=residual.log").body()).get("runs").size()).isEqualTo(1);
    }
    @Test void apiRejectsUnknownInvalidAndInflightReprocessingWithSafeExplicitErrors() throws Exception {
        var unknown=get("/api/run-versions/"+UUID.randomUUID());assertThat(unknown.statusCode()).isEqualTo(404);
        var invalid=get("/api/run-versions/not-uuid");assertThat(invalid.statusCode()).isEqualTo(400);assertThat(invalid.body()).doesNotContain(ROOT.toString());
        var batch=accept(true);String job=batch.jobs().getFirst().jobId();
        try(var client=HttpClient.newHttpClient()) {
            String url="http://localhost:"+port+"/api/import-jobs/"+job+"/reprocess";
            var missing=client.send(HttpRequest.newBuilder(URI.create(url)).POST(HttpRequest.BodyPublishers.noBody()).build(),HttpResponse.BodyHandlers.ofString());assertThat(missing.statusCode()).isEqualTo(400);
            var response=client.send(HttpRequest.newBuilder(URI.create(url)).header("Idempotency-Key","http-retry").POST(HttpRequest.BodyPublishers.noBody()).build(),HttpResponse.BodyHandlers.ofString());assertThat(response.statusCode()).isEqualTo(202);
            var retried=mapper.readTree(response.body());String newJob=retried.get("jobs").get(0).get("jobId").stringValue();
            var busy=client.send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/import-jobs/"+newJob+"/reprocess")).header("Idempotency-Key","busy").POST(HttpRequest.BodyPublishers.noBody()).build(),HttpResponse.BodyHandlers.ofString());assertThat(busy.statusCode()).isEqualTo(409);
            assertThat(mapper.readTree(busy.body()).get("code").stringValue()).isEqualTo("JOB_IN_PROGRESS");
            assertThat(mapper.readTree(busy.body()).get("requestId").stringValue()).isNotBlank();
        }
    }
    static Path temp() { try {return Files.createTempDirectory("run-query-");} catch(Exception e){throw new ExceptionInInitializerError(e);} }
    @AfterAll static void cleanup() throws Exception {try(var paths=Files.walk(ROOT)) {for(var p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);} }
}
