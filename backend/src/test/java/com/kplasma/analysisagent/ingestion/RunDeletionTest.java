package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.*;
import static org.assertj.core.api.Assertions.*;

/** Every original and database row in this suite is generated synthetic data. */
@Testcontainers
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="kplasma.worker.enabled=false")
class RunDeletionTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp("run-deletion-storage-"),UPLOADS=temp("run-deletion-originals-");
    static final String FIRST="RUN-P02-S100-B0000",SECOND="RUN-P04-S100-B0000";
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);
        r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString);
    }
    @Autowired ImportIntakeService intake;
    @Autowired SourceStore store;
    @Autowired ImportWorker worker;
    @Autowired ImportRecovery recovery;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    @LocalServerPort int port;
    @BeforeEach void clear() {
        jdbc.execute("truncate import_batch,source_set,run cascade");
        jdbc.execute("delete from conversation_turn");jdbc.execute("delete from decision");jdbc.execute("delete from workspace_idempotency");
        jdbc.update("update workspace set active_run=null,candidate_reference=null where id=1");
        SourceStore.cleanup(ROOT);SourceStore.cleanup(UPLOADS);
    }

    // Catches deletion of only the current version, stale job links, and old upload retries recreating deleted data.
    @Test void deletesEveryVersionAndOriginalButUploadRetryCannotRecreateDeletedRun() throws Exception {
        var first=process(accept(files("first",2,"v1"),"original-key"));
        process(accept(files("second",2,"v2"),"version-key"));
        process(accept(files("duplicate",2,"v1"),"duplicate-key"));
        process(worker.reprocess(UUID.fromString(first.jobs().getFirst().jobId()),"reprocess-key"));
        assertThat(count("run_version")).isEqualTo(3);
        Path original=UPLOADS.resolve("external-original.txt");Files.writeString(original,"user-owned original bytes");
        var result=delete(List.of(FIRST,FIRST,"RUN-P99-S999-B9999"));
        assertThat(result.get("deletedRunIds").size()).isEqualTo(1);
        assertThat(result.get("deletedRunIds").get(0).stringValue()).isEqualTo(FIRST);
        assertThat(result.get("cleanupPending").booleanValue()).isFalse();
        for(String table:List.of("run","run_version","import_job","source_set","source_file","import_batch_file","reprocess_idempotency"))assertThat(count(table)).as(table).isZero();
        assertThat(managedFiles()).isEmpty();
        assertThat(original).hasContent("user-owned original bytes");
        var replay=accept(files("first",2,"v1"),"original-key");
        assertThat(replay.batchId()).isEqualTo(first.batchId());assertThat(replay.jobs()).isEmpty();assertThat(replay.totalRuns()).isZero();
        assertThat(delete(List.of(FIRST)).get("deletedRunIds").size()).isZero();
        assertThat(process(accept(files("first",2,"v1"),"new-upload-key")).jobs().getFirst().status()).isEqualTo("READY");
    }

    // Catches deleting a whole mixed batch and leaking its deleted Run's ancillary originals.
    @Test void mixedBatchPreservesOtherRunAndFailedImportWithConsistentCounts() throws Exception {
        var files=files("remove",2,"remove");files.putAll(files("keep",4,"keep"));
        files.put("failed/0d_setting.ini",SyntheticRunFiles.ini(false));
        files.put("remove/.DS_Store","remove metadata");files.put("keep/.DS_Store","keep metadata");files.put("shared-notes.txt","batch notes");
        var batch=process(accept(files,"mixed"));
        var failed=batch.jobs().stream().filter(j->j.status().equals("INCOMPLETE")).findFirst().orElseThrow();
        var oldKeep=jdbc.queryForObject("select full_run::text from run_version where run_id=?",String.class,SECOND);
        delete(List.of(FIRST));
        var remaining=intake.get(batch.batchId());
        assertThat(remaining.jobs()).extracting(JobView::status).containsExactlyInAnyOrder("READY","INCOMPLETE");
        assertThat(remaining.totalRuns()).isEqualTo(2);assertThat(remaining.processedRuns()).isEqualTo(2);assertThat(remaining.status()).isEqualTo("PARTIAL_SUCCESS");
        assertThat(jdbc.queryForObject("select full_run::text from run_version where run_id=?",String.class,SECOND)).isEqualTo(oldKeep);
        assertThat(worker.files(UUID.fromString(failed.jobId()))).hasSize(1);
        assertThat(jdbc.queryForList("select relative_path from import_batch_file where batch_id=?::uuid",String.class,batch.batchId())).noneMatch(p->p.startsWith("remove/")).contains("shared-notes.txt","keep/.DS_Store");
        assertThat(managedFiles()).noneMatch(p->p.endsWith("remove/.DS_Store"));
    }

    // Catches ownership inferred from directory IDs: a surviving reprocess can own another batch's path.
    @Test void sharedPathsSurviveDeletionAndStartupCollection() throws Exception {
        var files=files("run",2,"shared");files.put("run/.DS_Store","shared metadata");
        var batch=process(accept(files,"shared"));
        var original=batch.jobs().getFirst();var retry=process(worker.reprocess(UUID.fromString(original.jobId()),"shared-retry"));
        UUID keptVersion=UUID.fromString(retry.jobs().getFirst().runVersionId());
        // Model a later parser version assigning the shared originals to a different display Run.
        jdbc.update("insert into run(run_id,current_version_id) values (?,?)",SECOND,keptVersion);
        jdbc.update("update run_version set run_id=? where id=?",SECOND,keptVersion);
        jdbc.update("update run set current_version_id=?::uuid where run_id=?",original.runVersionId(),FIRST);
        jdbc.update("update import_job set run_id=? where id=?::uuid",SECOND,retry.jobs().getFirst().jobId());
        var keptPaths=jdbc.queryForList("select storage_path from import_batch_file where batch_id=?::uuid",String.class,retry.batchId());
        assertThat(keptPaths).anyMatch(p->p.startsWith("batches/"+batch.batchId()+"/"));
        delete(List.of(FIRST));recovery.recover();
        assertThat(count("source_set")).isEqualTo(1);
        assertThat(worker.files(UUID.fromString(retry.jobs().getFirst().jobId()))).hasSize(5);
        keptPaths.forEach(p->assertThat(ROOT.resolve(p)).isRegularFile());
    }

    // Catches a racy per-Run active-job check: unparsed work has no run_id yet.
    @ParameterizedTest @ValueSource(strings={"QUEUED","PROCESSING"})
    void anyActiveImportBlocksDeletion(String status) throws Exception {
        process(accept(files("registered",2,"registered"),"registered"));
        var pending=accept(files("pending",4,"pending"),"pending");
        jdbc.update("update import_job set status=? where batch_id=?::uuid",status,pending.batchId());
        var response=post(Map.of("runIds",List.of(FIRST)));
        assertThat(response.statusCode()).isEqualTo(409);assertThat(json(response).get("code").stringValue()).isEqualTo("IMPORT_IN_PROGRESS");
        assertThat(count("run")).isEqualTo(1);assertThat(managedFiles()).isNotEmpty();
    }

    // Catches file deletion before the database transaction successfully commits.
    @Test void databaseFailureRollsBackAllSelectedRunsAndPreservesFiles() throws Exception {
        var files=files("first",2,"first");files.putAll(files("second",4,"second"));process(accept(files,"atomic"));
        var before=managedFiles();
        jdbc.execute("create function reject_delete() returns trigger language plpgsql as $$ begin raise exception 'synthetic deletion failure'; end $$");
        jdbc.execute("create trigger reject_delete before delete on run for each row execute function reject_delete()");
        try {
            assertThat(post(Map.of("runIds",List.of(FIRST,SECOND))).statusCode()).isEqualTo(503);
            assertThat(count("run_version")).isEqualTo(2);assertThat(count("import_job")).isEqualTo(2);assertThat(managedFiles()).containsExactlyInAnyOrderElementsOf(before);
        } finally {jdbc.execute("drop trigger reject_delete on run");jdbc.execute("drop function reject_delete()");}
    }

    // Catches reporting full cleanup success after an OS failure and failing to retry on restart.
    @Test void cleanupFailureIsReportedAndRecoveryRetriesAfterPermissionsReturn() throws Exception {
        process(accept(files("first",2,"permissions"),"permissions"));
        Path directory=ROOT.resolve(jdbc.queryForObject("select storage_path from source_file where relative_path='0d_setting.ini'",String.class)).getParent();
        Files.setPosixFilePermissions(directory,PosixFilePermissions.fromString("r-x------"));
        try {
            assertThat(delete(List.of(FIRST)).get("cleanupPending").booleanValue()).isTrue();assertThat(count("run")).isZero();assertThat(directory.resolve("0d_setting.ini")).exists();
        } finally {Files.setPosixFilePermissions(directory,PosixFilePermissions.fromString("rwx------"));}
        recovery.recover();assertThat(managedFiles()).isEmpty();
    }

    @Test void cleanupNeverFollowsSymlinksOutsideManagedStorage() throws Exception {
        process(accept(files("first",2,"links"),"links"));
        Path external=UPLOADS.resolve("keep.txt");Files.writeString(external,"external user original");
        Files.createSymbolicLink(ROOT.resolve("sources").resolve("outside"),UPLOADS);
        delete(List.of(FIRST));recovery.recover();assertThat(external).hasContent("external user original");
    }

    @Test void malformedOrUnboundedSelectionReturnsClientErrorWithoutDeletingAnything() throws Exception {
        process(accept(files("first",2,"validation"),"validation"));
        var selections=List.of(Map.of(),Map.of("runIds",List.of()),Map.of("runIds",List.of(" ")),Map.of("runIds",List.of("../escape")),Map.of("runIds",List.of(42)),Map.of("runIds",Collections.nCopies(1001,FIRST)),Map.of("runIds",List.of("x".repeat(65))));
        for(var body:selections)assertThat(post(body).statusCode()).as(body.toString()).isEqualTo(400);
        assertThat(count("run")).isEqualTo(1);
    }

    // A real held PostgreSQL lock gives a deterministic interleaving; no mocked transaction behavior.
    @Test void deletionWaitsForIntakePublicationAndThenRejectsTheNewQueuedJob() throws Exception {
        process(accept(files("registered",2,"lock"),"lock"));
        try(var connection=Objects.requireNonNull(jdbc.getDataSource()).getConnection();var executor=java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            connection.setAutoCommit(false);
            try(var statement=connection.createStatement()) {
                statement.execute("select pg_advisory_xact_lock(173529, 4)");
                var response=executor.submit(()->post(Map.of("runIds",List.of(FIRST))));
                try {
                    awaitDatabaseLock(response,"%pg_advisory_xact_lock(173529, 4)%");
                    statement.execute("insert into import_batch(id,status,received_bytes,total_bytes,total_runs) values ('11111111-1111-1111-1111-111111111111','QUEUED',0,0,1)");
                    statement.execute("insert into import_job(id,batch_id,source_id,source_root,status) select '22222222-2222-2222-2222-222222222222','11111111-1111-1111-1111-111111111111',id,'run/','QUEUED' from source_set limit 1");
                } finally {connection.commit();}
                assertThat(response.get().statusCode()).isEqualTo(409);assertThat(count("run")).isEqualTo(1);
            }
        }
    }

    @Test void deletionWaitsForWorkspaceMutationAndThenReleasesTheCommittedReference() throws Exception {
        var batch=process(accept(files("registered",2,"workspace-lock"),"workspace-lock"));
        var job=batch.jobs().getFirst();
        try(var connection=Objects.requireNonNull(jdbc.getDataSource()).getConnection();var executor=java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            connection.setAutoCommit(false);
            try(var statement=connection.createStatement()) {
                statement.execute("select id from workspace where id=1 for update");
                var response=executor.submit(()->post(Map.of("runIds",List.of(FIRST))));
                try {
                    awaitDatabaseLock(response,"%workspace%for update%");
                    try(var update=connection.prepareStatement("update workspace set active_run=?::jsonb where id=1")) {update.setString(1,mapper.writeValueAsString(Map.of("runId",FIRST,"runVersionId",job.runVersionId())));update.executeUpdate();}
                } finally {connection.commit();}
                assertThat(response.get().statusCode()).isEqualTo(200);assertThat(count("run")).isZero();
                assertThat(jdbc.queryForObject("select active_run is null from workspace where id=1",Boolean.class)).isTrue();
            }
        }
    }

    private void awaitDatabaseLock(java.util.concurrent.Future<HttpResponse<String>> response,String query) throws Exception {
        long deadline=System.nanoTime()+java.time.Duration.ofSeconds(5).toNanos();
        while(System.nanoTime()<deadline) {
            if(response.isDone())fail("Deletion returned before acquiring the required lock: "+response.get().statusCode());
            if(Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like ?)",Boolean.class,query)))return;
            Thread.sleep(10);
        }
        fail("Deletion did not wait on the required PostgreSQL lock");
    }

    private BatchView accept(Map<String,String> contents,String key) throws Exception {
        Files.createDirectories(UPLOADS);List<UploadEntry> entries=new ArrayList<>();List<UploadPart> parts=new ArrayList<>();
        for(var entry:contents.entrySet()) {String name="f"+entries.size();Path path=Files.createTempFile(UPLOADS,"synthetic-",".txt");Files.writeString(path,entry.getValue());entries.add(new UploadEntry(name,entry.getKey()));parts.add(new UploadPart(name,path,Files.size(path)));}
        return intake.accept(store.stage(new UploadManifest("FOLDER",entries),parts),key);
    }
    private BatchView process(BatchView batch) {batch.jobs().forEach(j->worker.process(UUID.fromString(j.jobId())));return intake.get(batch.batchId());}
    private Map<String,String> files(String root,int pressure,String marker) {Map<String,String> files=new LinkedHashMap<>();SyntheticRunFiles.files(marker).forEach((p,v)->files.put(root+"/"+p,v.replace("PRS=2","PRS="+pressure).replace("Pressure = 2 (","Pressure = "+pressure+" (")));return files;}
    private int count(String table){return jdbc.queryForObject("select count(*) from "+table,Integer.class);}
    private List<String> managedFiles() throws Exception {if(!Files.exists(ROOT))return List.of();try(var files=Files.walk(ROOT)){return files.filter(p->Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)).filter(p->p.startsWith(ROOT.resolve("sources"))||p.startsWith(ROOT.resolve("batches"))).map(ROOT::relativize).map(Path::toString).sorted().toList();}}
    private HttpResponse<String> post(Object body) throws Exception {return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/api/runs/delete")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());}
    private JsonNode json(HttpResponse<String> response){return mapper.readTree(response.body());}
    private JsonNode delete(List<String> ids) throws Exception {var response=post(Map.of("runIds",ids));assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);}
    static Path temp(String prefix){try{return Files.createTempDirectory(prefix);}catch(Exception e){throw new ExceptionInInitializerError(e);}}
    @AfterAll static void cleanup(){SourceStore.cleanup(ROOT);SourceStore.cleanup(UPLOADS);}
}
