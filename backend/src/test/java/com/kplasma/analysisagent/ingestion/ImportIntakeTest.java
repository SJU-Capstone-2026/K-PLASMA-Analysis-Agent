package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.jayway.jsonpath.JsonPath;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ImportIntakeTest {
    @Container static final PostgreSQLContainer DB = new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT = temp();
    @LocalServerPort int port;
    @Autowired ImportIntakeService intake;
    @Autowired SourceStore store;
    @Autowired JdbcTemplate jdbc;
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", DB::getJdbcUrl); r.add("spring.datasource.username", DB::getUsername);
        r.add("spring.datasource.password", DB::getPassword); r.add("kplasma.storage-root", ROOT::toString);
        r.add("spring.servlet.multipart.location", () -> ROOT.resolve("servlet").toString());
    }
    private StoredBatch batch(String contents) throws Exception {
        Path upload = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(upload, contents);
        return store.stage(new UploadManifest("FOLDER", List.of(new UploadEntry("file", "run/0d_setting.ini"))), List.of(new UploadPart("file", upload, 0)));
    }
    @Test void retainsSourceBeforeQueueingAndReplayDoesNotCreateAnotherJob() throws Exception {
        var first = intake.accept(batch("synthetic persisted input"), "first-key");
        assertThat(first.status()).isEqualTo("QUEUED"); assertThat(first.jobs()).hasSize(1);
        assertThat(first.jobs().getFirst().status()).isEqualTo("QUEUED");
        assertThat(first.jobs().getFirst().runVersionId()).isNull();
        assertThat(intake.get(first.batchId())).isEqualTo(first);
        assertThat(jdbc.queryForObject("select count(*) from import_job where batch_id = ?::uuid", Integer.class, first.batchId())).isEqualTo(1);
        String stored = jdbc.queryForObject("select storage_path from source_file where source_id = (select source_id from import_job where id = ?::uuid)", String.class, first.jobs().getFirst().jobId());
        assertThat(Files.readString(ROOT.resolve(stored))).isEqualTo("synthetic persisted input");
        assertThat(intake.accept(batch("synthetic persisted input"), "first-key")).isEqualTo(first);
        assertThatThrownBy(() -> intake.accept(batch("changed"), "first-key")).isInstanceOf(IntakeException.class).hasMessageContaining("idempotency");
        try (var staged = Files.list(ROOT.resolve("staging"))) { assertThat(staged.count()).isZero(); }
    }
    @Test void duplicateSourceReusesOriginalStorageAcrossNewBatches() throws Exception {
        var first = intake.accept(batch("same source"), "dup-1");
        var second = intake.accept(batch("same source"), "dup-2");
        assertThat(first.batchId()).isNotEqualTo(second.batchId());
        assertThat(jdbc.queryForObject("select count(*) from source_set where sha256 = (select sha256 from source_set where id = (select source_id from import_job where id = ?::uuid))", Integer.class, first.jobs().getFirst().jobId())).isEqualTo(1);
        assertThat(second.jobs().getFirst().status()).isEqualTo("QUEUED");
    }
    @Test void accepts5000FilesPlusManifestOverRealHttpAndReturnsCleanErrors() throws Exception {
        String boundary = "synthetic-intake-boundary";
        var body = new StringBuilder(); var manifest = new StringBuilder("{\"mode\":\"FOLDER\",\"entries\":[");
        for (int i = 0; i < 5000; i++) {
            if (i > 0) manifest.append(',');
            manifest.append("{\"partName\":\"f").append(i).append("\",\"relativePath\":\"run/").append(i == 0 ? "0d_setting.ini" : "extra/" + i + ".txt").append("\"}");
        }
        manifest.append("]}");
        body.append("--").append(boundary).append("\r\nContent-Disposition: form-data; name=\"manifest\"\r\nContent-Type: application/json\r\n\r\n").append(manifest).append("\r\n");
        for (int i = 0; i < 5000; i++) body.append("--").append(boundary).append("\r\nContent-Disposition: form-data; name=\"f").append(i).append("\"; filename=\"f.txt\"\r\nContent-Type: application/octet-stream\r\n\r\nx\r\n");
        body.append("--").append(boundary).append("--\r\n");
        try (var client = HttpClient.newHttpClient()) {
            var response = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches")).header("Content-Type", "multipart/form-data; boundary=" + boundary).header("Idempotency-Key", "5000-http").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).withFailMessage(response.body()).isEqualTo(202);
            assertThat(JsonPath.<Integer>read(response.body(), "$.totalRuns")).isEqualTo(1);
            assertThat(JsonPath.<Integer>read(response.body(), "$.receivedBytes")).isEqualTo(5000);
            assertThat(response.body()).doesNotContain(ROOT.toString()).doesNotContain("READY");
            var missing = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches/" + UUID.randomUUID())).GET().build(), HttpResponse.BodyHandlers.ofString());
            assertThat(missing.statusCode()).isEqualTo(404);
            assertThat(JsonPath.<String>read(missing.body(), "$.code")).isEqualTo("NOT_FOUND");
            assertThat(JsonPath.<String>read(missing.body(), "$.requestId")).isNotBlank();
        }
        try (var staged = Files.list(ROOT.resolve("staging"))) { assertThat(staged.count()).isZero(); }
        try (var uploads = Files.list(ROOT.resolve("uploads"))) { assertThat(uploads.count()).isZero(); }
    }
    @Test void failedDatabasePublicationRollsBackAndRemovesPromotedOriginals() throws Exception {
        int sourceCount = jdbc.queryForObject("select count(*) from source_set", Integer.class);
        long directoryCount;
        if (Files.exists(ROOT.resolve("sources"))) { try (var paths = Files.list(ROOT.resolve("sources"))) { directoryCount = paths.count(); } } else directoryCount = 0;
        jdbc.execute("create function reject_test_intake() returns trigger language plpgsql as $$ begin if new.idempotency_key = 'rollback-key' then raise exception 'synthetic publication failure'; end if; return new; end $$");
        jdbc.execute("create trigger reject_test_intake before insert on import_idempotency for each row execute function reject_test_intake()");
        try {
            assertThatThrownBy(() -> intake.accept(batch("unique rollback bytes"), "rollback-key")).isInstanceOf(org.springframework.dao.DataAccessException.class);
            assertThat(jdbc.queryForObject("select count(*) from source_set", Integer.class)).isEqualTo(sourceCount);
            assertThat(jdbc.queryForObject("select count(*) from import_idempotency where idempotency_key = 'rollback-key'", Integer.class)).isZero();
            try (var paths = Files.list(ROOT.resolve("sources"))) { assertThat(paths.count()).isEqualTo(directoryCount); }
            try (var paths = Files.list(ROOT.resolve("staging"))) { assertThat(paths.count()).isZero(); }
        } finally { jdbc.execute("drop trigger reject_test_intake on import_idempotency"); jdbc.execute("drop function reject_test_intake()"); }
    }
    @Test void concurrentReplayPublishesExactlyOneBatchAndJob() throws Exception {
        var a = batch("concurrent original"); var b = batch("concurrent original");
        try (var executor = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            var first = executor.submit(() -> intake.accept(a, "concurrent-key"));
            var second = executor.submit(() -> intake.accept(b, "concurrent-key"));
            assertThat(first.get()).isEqualTo(second.get());
        }
        assertThat(jdbc.queryForObject("select count(*) from import_job where batch_id = (select batch_id from import_idempotency where idempotency_key = 'concurrent-key')", Integer.class)).isEqualTo(1);
        try (var paths = Files.list(ROOT.resolve("staging"))) { assertThat(paths.count()).isZero(); }
    }
    @Test void rejectsOversizedManifestBeforeAttemptingJsonDeserialization() throws Exception {
        String boundary = "manifest-limit-boundary";
        String body = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"manifest\"; filename=\"manifest.json\"\r\nContent-Type: application/json\r\n\r\n" + "x".repeat(8 * 1024 * 1024 + 1) + "\r\n--" + boundary + "--\r\n";
        try (var client = HttpClient.newHttpClient()) {
            var response = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches")).header("Content-Type", "multipart/form-data; boundary=" + boundary).header("Idempotency-Key", "metadata-limit").POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).withFailMessage(response.body()).isEqualTo(413);
            assertThat(JsonPath.<String>read(response.body(), "$.code")).isEqualTo("UPLOAD_LIMIT_EXCEEDED");
        }
    }
    @Test void actualHttpArchiveLargerThan64MiBIsAcceptedAndRetained() throws Exception {
        Path archive = Files.createTempFile(ROOT, "large-http-", ".zip");
        try (var out = new java.util.zip.ZipOutputStream(Files.newOutputStream(archive))) {
            byte[] chunk = new byte[1024 * 1024]; new Random(83).nextBytes(chunk);
            for (int n = 0; n < 65; n++) {
                out.putNextEntry(new java.util.zip.ZipEntry(n == 0 ? "0d_setting.ini" : "auxiliary/" + n + ".txt"));
                out.write(chunk); out.closeEntry();
            }
        }
        assertThat(Files.size(archive)).isGreaterThan(64L * 1024 * 1024);
        String boundary = "large-archive-boundary";
        String prefix = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"manifest\"\r\nContent-Type: application/json\r\n\r\n{\"mode\":\"ZIP\",\"entries\":[{\"partName\":\"archive\",\"relativePath\":\"original.zip\"}]}\r\n--" + boundary + "\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"original.zip\"\r\nContent-Type: application/zip\r\n\r\n";
        try (var client = HttpClient.newHttpClient()) {
            var publisher = HttpRequest.BodyPublishers.concat(HttpRequest.BodyPublishers.ofString(prefix), HttpRequest.BodyPublishers.ofFile(archive), HttpRequest.BodyPublishers.ofString("\r\n--" + boundary + "--\r\n"));
            var response = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches")).header("Content-Type", "multipart/form-data; boundary=" + boundary).header("Idempotency-Key", "large-http-zip").POST(publisher).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).withFailMessage(response.body()).isEqualTo(202);
            assertThat(JsonPath.<Integer>read(response.body(), "$.totalBytes")).isEqualTo(65 * 1024 * 1024);
            assertThat(JsonPath.<String>read(response.body(), "$.jobs[0].status")).isEqualTo("QUEUED");
        } finally { Files.deleteIfExists(archive); }
        try (var paths = Files.list(ROOT.resolve("uploads"))) { assertThat(paths.count()).isZero(); }
    }
    @Test void rejectsTraversalOverHttpAndCleansServletAndOwnedTemporaryFiles() throws Exception {
        String boundary = "traversal-boundary";
        String body = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"manifest\"\r\nContent-Type: application/json\r\n\r\n{\"mode\":\"FOLDER\",\"entries\":[{\"partName\":\"file\",\"relativePath\":\"../escape\"}]}\r\n--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"file.txt\"\r\nContent-Type: application/octet-stream\r\n\r\nbytes\r\n--" + boundary + "--\r\n";
        try (var client = HttpClient.newHttpClient()) {
            var response = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches")).header("Content-Type", "multipart/form-data; boundary=" + boundary).header("Idempotency-Key", "traversal-http").POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).withFailMessage(response.body()).isEqualTo(400);
            assertThat(JsonPath.<String>read(response.body(), "$.code")).isEqualTo("INVALID_UPLOAD");
            assertThat(response.body()).doesNotContain(ROOT.toString());
        }
        try (var paths = Files.list(ROOT.resolve("uploads"))) { assertThat(paths.count()).isZero(); }
        try (var paths = Files.list(ROOT.resolve("servlet"))) { assertThat(paths.count()).isZero(); }
    }
    @Test void requiresIdempotencyHeaderAndExposesReplayAndConflictOverHttp() throws Exception {
        String boundary = "idempotency-boundary";
        String template = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"manifest\"\r\nContent-Type: application/json\r\n\r\n{\"mode\":\"FOLDER\",\"entries\":[{\"partName\":\"file\",\"relativePath\":\"run/0d_setting.ini\"}]}\r\n--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"file.txt\"\r\nContent-Type: application/octet-stream\r\n\r\n%s\r\n--" + boundary + "--\r\n";
        try (var client = HttpClient.newHttpClient()) {
            var base = HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/import-batches")).header("Content-Type", "multipart/form-data; boundary=" + boundary);
            var missing = client.send(base.copy().POST(HttpRequest.BodyPublishers.ofString(template.formatted("original"))).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(missing.statusCode()).isEqualTo(400);
            assertThat(JsonPath.<String>read(missing.body(), "$.code")).isEqualTo("INVALID_UPLOAD");
            var accepted = client.send(base.copy().header("Idempotency-Key", "http-replay").POST(HttpRequest.BodyPublishers.ofString(template.formatted("original"))).build(), HttpResponse.BodyHandlers.ofString());
            var replay = client.send(base.copy().header("Idempotency-Key", "http-replay").POST(HttpRequest.BodyPublishers.ofString(template.formatted("original"))).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(accepted.statusCode()).isEqualTo(202); assertThat(replay.statusCode()).isEqualTo(202);
            assertThat(replay.body()).isEqualTo(accepted.body());
            var conflict = client.send(base.copy().header("Idempotency-Key", "http-replay").POST(HttpRequest.BodyPublishers.ofString(template.formatted("changed"))).build(), HttpResponse.BodyHandlers.ofString());
            assertThat(conflict.statusCode()).isEqualTo(409);
            assertThat(JsonPath.<String>read(conflict.body(), "$.code")).isEqualTo("IDEMPOTENCY_CONFLICT");
            assertThat(JsonPath.<String>read(conflict.body(), "$.requestId")).isNotBlank();
        }
        try (var paths = Files.list(ROOT.resolve("uploads"))) { assertThat(paths.count()).isZero(); }
        try (var paths = Files.list(ROOT.resolve("staging"))) { assertThat(paths.count()).isZero(); }
    }
    @Test void failedPromotionNeverCleansAnExternalDirectoryThroughStorageSymlink() throws Exception {
        Path one = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(one, "symlink regression setting");
        Path two = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(two, "ancillary original");
        var staged = store.stage(new UploadManifest("FOLDER", List.of(new UploadEntry("one", "run/0d_setting.ini"), new UploadEntry("two", "ancillary.txt"))), List.of(new UploadPart("one", one, 0), new UploadPart("two", two, 0)));
        Path outside = Files.createTempDirectory("intake-external-");
        Path externalBatch = Files.createDirectory(outside.resolve(staged.batchId().toString()));
        Path marker = Files.writeString(externalBatch.resolve("keep.txt"), "must remain unchanged");
        Path batches = ROOT.resolve("batches");
        Path backup = ROOT.resolve("batches-backup-" + UUID.randomUUID());
        boolean hadBatches = Files.exists(batches);
        if (hadBatches) Files.move(batches, backup);
        Files.createSymbolicLink(batches, outside);
        try {
            assertThatThrownBy(() -> intake.accept(staged, "symlink-promotion")).isInstanceOf(IntakeException.class);
            assertThat(marker).exists(); assertThat(Files.readString(marker)).isEqualTo("must remain unchanged");
            assertThat(jdbc.queryForObject("select count(*) from import_batch where id = ?", Integer.class, staged.batchId())).isZero();
            assertThat(staged.stagingRoot()).doesNotExist();
        } finally {
            Files.deleteIfExists(batches);
            if (hadBatches) Files.move(backup, batches);
            try (var paths = Files.walk(outside)) { for (var path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path); }
        }
    }
    @Test void preservesAncillaryAndOsMetadataAlongsideTheNormalizedRunSource() throws Exception {
        Path setting = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(setting, "ancillary regression setting");
        Path metadata = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(metadata, "OS metadata");
        Path notes = Files.createTempFile(ROOT, "upload-", ".tmp"); Files.writeString(notes, "original notes");
        var staged = store.stage(new UploadManifest("FOLDER", List.of(new UploadEntry("setting", "run/0d_setting.ini"), new UploadEntry("metadata", "run/.DS_Store"), new UploadEntry("notes", "notes.txt"))), List.of(new UploadPart("setting", setting, 0), new UploadPart("metadata", metadata, 0), new UploadPart("notes", notes, 0)));
        var view = intake.accept(staged, "ancillary-originals");
        assertThat(jdbc.queryForObject("select count(*) from import_batch_file where batch_id = ?::uuid", Integer.class, view.batchId())).isEqualTo(3);
        assertThat(jdbc.queryForObject("select count(*) from source_file where source_id = (select source_id from import_job where id = ?::uuid)", Integer.class, view.jobs().getFirst().jobId())).isEqualTo(1);
        var originals = jdbc.queryForList("select relative_path, storage_path from import_batch_file where batch_id = ?::uuid", view.batchId());
        Map<String, String> expected = Map.of("run/0d_setting.ini", "ancillary regression setting", "run/.DS_Store", "OS metadata", "notes.txt", "original notes");
        for (var original : originals) assertThat(Files.readString(ROOT.resolve((String) original.get("storage_path")))).isEqualTo(expected.get(original.get("relative_path")));
        assertThat(staged.stagingRoot()).doesNotExist();
    }
    @AfterAll static void cleanup() throws Exception { try (var paths = Files.walk(ROOT)) { for (var p : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(p); } }
    private static Path temp() { try { Path root = Files.createTempDirectory("intake-"); Files.createDirectory(root.resolve("servlet")); return root; } catch (Exception e) { throw new ExceptionInInitializerError(e); } }
}
