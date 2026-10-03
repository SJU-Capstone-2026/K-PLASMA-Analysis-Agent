package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.run.RunQueryService;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
@SpringBootTest(properties="kplasma.worker.enabled=false")
class ImportPipelineTest {
    @Container static final PostgreSQLContainer DB = new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT = temp();
    @Autowired ImportIntakeService intake;
    @Autowired SourceStore store;
    @Autowired ImportWorker worker;
    @Autowired ImportRecovery recovery;
    @Autowired RunQueryService query;
    @Autowired JdbcTemplate jdbc;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url",DB::getJdbcUrl); r.add("spring.datasource.username",DB::getUsername);
        r.add("spring.datasource.password",DB::getPassword); r.add("kplasma.storage-root",ROOT::toString);
    }
    @BeforeEach void clear() { jdbc.execute("truncate import_batch, source_set, run cascade"); }
    private StoredBatch batch(Map<String,String> contents, boolean zip) throws Exception {
        if(zip) {
            Path archive=Files.createTempFile(ROOT,"synthetic-",".zip");
            try(var out=new java.util.zip.ZipOutputStream(Files.newOutputStream(archive))) {
                for(var e:contents.entrySet()) { out.putNextEntry(new java.util.zip.ZipEntry(e.getKey())); out.write(e.getValue().getBytes(java.nio.charset.StandardCharsets.UTF_8)); out.closeEntry(); }
            }
            return store.stage(new UploadManifest("ZIP",List.of(new UploadEntry("zip","original.zip"))),List.of(new UploadPart("zip",archive,Files.size(archive))));
        }
        List<UploadEntry> entries=new ArrayList<>(); List<UploadPart> parts=new ArrayList<>();
        for(var e:contents.entrySet()) { String name="f"+entries.size(); Path p=Files.createTempFile(ROOT,"synthetic-",".txt"); Files.writeString(p,e.getValue()); entries.add(new UploadEntry(name,e.getKey())); parts.add(new UploadPart(name,p,Files.size(p))); }
        return store.stage(new UploadManifest("FOLDER",entries),parts);
    }
    private Map<String,String> run(String prefix,String marker) { Map<String,String> files=new HashMap<>(); SyntheticRunFiles.files(marker).forEach((p,v)->files.put(prefix+"/"+p,v)); return files; }
    private BatchView accept(String marker) throws Exception { return intake.accept(batch(run("run",marker),false),UUID.randomUUID().toString()); }
    private BatchView process(BatchView view) { view.jobs().forEach(j->worker.process(UUID.fromString(j.jobId()))); return intake.get(view.batchId()); }

    @Test void oneSuccessAndOneMissingRunProducesPartialSuccessAndOneSearchableRun() throws Exception {
        Map<String,String> files=run("good","first"); files.put("missing/0d_setting.ini",SyntheticRunFiles.ini(false));
        var accepted=intake.accept(batch(files,false),"partial");
        worker.process(UUID.fromString(accepted.jobs().getFirst().jobId()));
        assertThat(intake.get(accepted.batchId()).status()).isEqualTo("PROCESSING");
        assertThat(intake.get(accepted.batchId()).processedRuns()).isEqualTo(1);
        var done=process(accepted);
        assertThat(done.status()).isEqualTo("PARTIAL_SUCCESS"); assertThat(done.processedRuns()).isEqualTo(2);
        assertThat(done.jobs()).extracting(JobView::status).containsExactlyInAnyOrder("READY","INCOMPLETE");
        assertThat(query.listSearchable()).hasSize(1); assertThat(query.listSearchable().getFirst().runId()).isEqualTo("RUN-P02-S100-B0000");
        assertThat(done.jobs().stream().filter(j->j.status().equals("INCOMPLETE")).findFirst().orElseThrow().errors()).isNotEmpty();
    }
    @Test void folderAndZipEquivalentOriginalsAreDuplicateWithoutCreatingVersion() throws Exception {
        var first=process(accept("duplicate")); var second=process(intake.accept(batch(run("wrapped","duplicate"),true),"zip"));
        assertThat(second.status()).isEqualTo("SUCCESS"); assertThat(second.jobs().getFirst().status()).isEqualTo("DUPLICATE");
        assertThat(second.jobs().getFirst().runVersionId()).isEqualTo(first.jobs().getFirst().runVersionId());
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(1);
    }
    @Test void changedOriginalPublishesNewVersionAndFailedNewestPreservesPreviousSuccess() throws Exception {
        var first=process(accept("v1")); var second=process(accept("v2"));
        String v1=first.jobs().getFirst().runVersionId(),v2=second.jobs().getFirst().runVersionId();
        assertThat(v2).isNotEqualTo(v1); assertThat(query.listSearchable().getFirst().runVersionId()).isEqualTo(v2);
        assertThat(query.getVersion(UUID.fromString(v1)).runVersionId()).isEqualTo(v1);
        var broken=run("run","v3"); broken.remove("run/0d_result/log/output.log");
        assertThat(process(intake.accept(batch(broken,false),"broken")).status()).isEqualTo("FAILED");
        assertThat(query.listSearchable().getFirst().runVersionId()).isEqualTo(v2);
    }
    @Test void recoveryInterruptsProcessingAndReprocessUsesSameOriginalWithNewImmutableVersion() throws Exception {
        var first=process(accept("recover")); var retry=worker.reprocess(UUID.fromString(first.jobs().getFirst().jobId()),"retry");
        UUID retryId=UUID.fromString(retry.jobs().getFirst().jobId());
        jdbc.update("update import_job set status='PROCESSING' where id=?",retryId);
        recovery.recover(); assertThat(intake.get(retry.batchId()).jobs().getFirst().status()).isEqualTo("INTERRUPTED");
        var second=worker.reprocess(retryId,"retry2"); assertThat(worker.reprocess(retryId,"retry2")).isEqualTo(second);
        second=process(second); assertThat(second.jobs().getFirst().status()).isEqualTo("READY");
        assertThat(second.jobs().getFirst().runVersionId()).isNotEqualTo(first.jobs().getFirst().runVersionId());
        assertThat(jdbc.queryForObject("select count(distinct source_id) from import_job",Integer.class)).isEqualTo(1);
        assertThat(query.getVersion(UUID.fromString(first.jobs().getFirst().runVersionId())).runVersionId()).isEqualTo(first.jobs().getFirst().runVersionId());
    }
    @Test void registrationFailureRollsBackVersionAndCurrentPointerTogether() throws Exception {
        var first=process(accept("atomic1")); var second=accept("atomic2");
        jdbc.execute("create function reject_run_update() returns trigger language plpgsql as $$ begin raise exception 'synthetic atomic failure'; end $$");
        jdbc.execute("create trigger reject_run_update before update on run for each row execute function reject_run_update()");
        try {
            process(second);
            assertThat(intake.get(second.batchId()).jobs().getFirst().status()).isEqualTo("PARSE_FAILED");
            assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(1);
            assertThat(query.listSearchable().getFirst().runVersionId()).isEqualTo(first.jobs().getFirst().runVersionId());
        } finally { jdbc.execute("drop trigger reject_run_update on run"); jdbc.execute("drop function reject_run_update()"); }
    }
    @Test void recoveryCleansOnlyUnreferencedDirectoriesAndNeverKnownOriginalsOrSymlinkTargets() throws Exception {
        var first=accept("retained");
        Path known=ROOT.resolve("sources").resolve(jdbc.queryForObject("select source_id from import_job where id=?::uuid",UUID.class,first.jobs().getFirst().jobId()).toString());
        Path orphan=Files.createDirectory(ROOT.resolve("sources").resolve(UUID.randomUUID().toString())); Files.writeString(orphan.resolve("orphan"),"bytes");
        Path staging=Files.createTempDirectory(ROOT.resolve("staging"),"abandoned-"); Files.writeString(staging.resolve("part"),"bytes");
        Path outside=Files.createTempDirectory("recovery-outside-"); Path marker=Files.writeString(outside.resolve("keep"),"keep");
        Path link=ROOT.resolve("sources").resolve(UUID.randomUUID().toString()); Files.createSymbolicLink(link,outside);
        try { recovery.recover(); assertThat(known.resolve("0d_setting.ini")).exists(); assertThat(orphan).doesNotExist(); assertThat(staging).doesNotExist(); assertThat(marker).exists(); }
        finally { Files.deleteIfExists(link); SourceStore.cleanup(outside); }
    }
    @Test void jobManifestKeepsOnlyExactRunLineageIncludingOsAndAncillaryFilesThroughReprocess() throws Exception {
        var files=run("run","manifest1");files.putAll(run("run-extra","manifest2"));
        files.put("run/.DS_Store","OS original");files.put("run/notes.txt","inside original");files.put("root-notes.txt","batch original");
        var batch=intake.accept(batch(files,false),"scoped-manifest");
        UUID job=jdbc.queryForObject("select id from import_job where batch_id=?::uuid and source_root='run/'",UUID.class,batch.batchId());
        var original=worker.files(job);
        assertThat(original).hasSize(6);assertThat(original).extracting(ManifestFile::path).contains("run/.DS_Store","run/notes.txt","run/0d_result/log/output.log").doesNotContain("root-notes.txt","run-extra/0d_setting.ini");
        worker.process(job);var retry=worker.reprocess(job,"scoped-retry");
        assertThat(worker.files(UUID.fromString(retry.jobs().getFirst().jobId()))).isEqualTo(original);
        assertThat(jdbc.queryForObject("select count(*) from import_batch_file where batch_id=?::uuid",Integer.class,retry.batchId())).isEqualTo(6);
        assertThat(jdbc.queryForObject("select count(*) from import_batch_file where batch_id=?::uuid",Integer.class,batch.batchId())).isEqualTo(11);
    }
    @Test void rootSelectedRunKeepsItsEntireUploadedManifest() throws Exception {
        var files=new HashMap<>(SyntheticRunFiles.files("root-manifest"));files.put(".DS_Store","OS original");files.put("notes.txt","inside original");
        var batch=intake.accept(batch(files,false),"root-manifest");
        assertThat(worker.files(UUID.fromString(batch.jobs().getFirst().jobId()))).hasSize(6);
    }
    static Path temp() { try { return Files.createTempDirectory("pipeline-"); } catch(Exception e) { throw new ExceptionInInitializerError(e); } }
    @AfterAll static void cleanup() { SourceStore.cleanup(ROOT); }
}
