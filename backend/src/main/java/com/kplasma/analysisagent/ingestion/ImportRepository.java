package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.contract.WorkspaceDto;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

/** JDBC persistence participates in the service's Spring transaction; the worker may use the same tables. */
@Repository
public class ImportRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    public ImportRepository(JdbcTemplate jdbc, ObjectMapper mapper) { this.jdbc = jdbc; this.mapper = mapper; }
    void lockIntake() { jdbc.queryForList("select pg_advisory_xact_lock(173529, 4)"); }
    record Replay(UUID batchId, String requestHash) {}
    Replay replay(String key) {
        var results = jdbc.query("select batch_id, request_hash from import_idempotency where idempotency_key = ?", (rs, n) -> new Replay(rs.getObject(1, UUID.class), rs.getString(2)), key);
        return results.isEmpty() ? null : results.getFirst();
    }
    UUID sourceByHash(String hash) {
        var results = jdbc.query("select id from source_set where sha256 = ?", (rs, n) -> rs.getObject(1, UUID.class), hash);
        return results.isEmpty() ? null : results.getFirst();
    }
    Map<String, String> sourcePaths(UUID id) {
        Map<String, String> paths = new HashMap<>();
        jdbc.query("select relative_path, storage_path from source_file where source_id = ?", rs -> { paths.put(rs.getString(1), rs.getString(2)); }, id);
        return paths;
    }
    void saveSource(StoredSource source, Map<String, String> storagePaths) {
        jdbc.update("insert into source_set(id, sha256, total_bytes) values (?, ?, ?)", source.sourceId(), source.sha256(), source.files().values().stream().mapToLong(StoredBatch.File::size).sum());
        jdbc.batchUpdate("insert into source_file(source_id, relative_path, kind, size, sha256, storage_path) values (?, ?, ?, ?, ?, ?)", source.files().entrySet().stream().map(e -> new Object[]{source.sourceId(), e.getKey(), e.getValue().kind(), e.getValue().size(), e.getValue().sha256(), storagePaths.get(e.getKey())}).toList());
    }
    void saveBatch(StoredBatch batch, int totalRuns) {
        jdbc.update("insert into import_batch(id, status, received_bytes, total_bytes, total_runs) values (?, 'QUEUED', ?, ?, ?)", batch.batchId(), batch.receivedBytes(), batch.totalBytes(), totalRuns);
    }
    void saveJob(UUID batch, UUID source, String root) {
        jdbc.update("insert into import_job(id, batch_id, source_id, source_root, status) values (?, ?, ?, ?, 'QUEUED')", UUID.randomUUID(), batch, source, root);
    }
    void saveBatchFiles(StoredBatch batch, Map<String, String> paths) {
        jdbc.batchUpdate("insert into import_batch_file(batch_id, relative_path, size, sha256, kind, storage_path) values (?, ?, ?, ?, ?, ?)", batch.files().stream().map(f -> new Object[]{batch.batchId(), f.relativePath(), f.size(), f.sha256(), f.kind(), paths.get(f.relativePath())}).toList());
    }
    void saveIdempotency(String key, String hash, UUID batch) {
        jdbc.update("insert into import_idempotency(idempotency_key, request_hash, batch_id) values (?, ?, ?)", key, hash, batch);
    }
    public BatchView get(UUID id) {
        var jobs = jdbc.query("select id, run_id, run_version_id, status, reason, errors from import_job where batch_id = ? order by created_at, id", (rs, n) -> new JobView(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4), rs.getString(5), mapper.readValue(rs.getString(6), new TypeReference<List<WorkspaceDto.Error>>() {})), id);
        var batches = jdbc.query("select id, status, received_bytes, total_bytes, processed_runs, total_runs from import_batch where id = ?", (rs, n) -> new BatchView(rs.getString(1), rs.getString(2), rs.getLong(3), rs.getLong(4), rs.getInt(5), rs.getInt(6), jobs), id);
        if (batches.isEmpty()) throw new IntakeException("NOT_FOUND", 404, "Import batch not found");
        return batches.getFirst();
    }
}
