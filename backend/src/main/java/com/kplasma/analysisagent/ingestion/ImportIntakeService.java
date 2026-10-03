package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.BatchView;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ImportIntakeService {
    private final SourceStore store;
    private final RunSourceDiscovery discovery;
    private final ImportRepository repository;
    private final TransactionTemplate transactions;
    public ImportIntakeService(SourceStore store, RunSourceDiscovery discovery, ImportRepository repository, PlatformTransactionManager transactionManager) {
        this.store = store; this.discovery = discovery; this.repository = repository;
        this.transactions = new TransactionTemplate(transactionManager);
    }
    public BatchView accept(StoredBatch batch, String idempotencyKey) {
        List<Path> newlyRetained = new ArrayList<>();
        try {
            if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 200)
                throw IntakeException.invalid("A valid idempotency key is required");
            var sources = discovery.discover(batch);
            Map<String, StoredBatch.File> manifest = new TreeMap<>();
            batch.files().forEach(file -> manifest.put(file.relativePath(), file));
            String hash = SourceStore.hashFiles(manifest);
            return transactions.execute(status -> {
                // Serialize intake publication, including filesystem promotion, to avoid duplicate-source races.
                repository.lockIntake();
                var replay = repository.replay(idempotencyKey);
                if (replay != null) {
                    if (!replay.requestHash().equals(hash)) throw new IntakeException("IDEMPOTENCY_CONFLICT", 409, "idempotency key was used for different originals");
                    return repository.get(replay.batchId());
                }
                repository.saveBatch(batch, sources.size());
                Map<String, String> retained = new HashMap<>();
                for (var source : sources) {
                    UUID id = repository.sourceByHash(source.sha256());
                    Map<String, String> sourcePaths;
                    if (id == null) {
                        id = source.sourceId(); sourcePaths = new TreeMap<>();
                        Path destination = store.root().resolve("sources").resolve(id.toString());
                        try { store.safeDirectory(destination); } catch (IOException e) { throw new UncheckedIOException(e); }
                        newlyRetained.add(destination);
                        for (var entry : source.files().entrySet()) {
                            Path target = destination.resolve(entry.getKey()); move(entry.getValue().path(), target);
                            sourcePaths.put(entry.getKey(), store.root().relativize(target).toString().replace('\\', '/'));
                        }
                        repository.saveSource(source, sourcePaths);
                    } else sourcePaths = repository.sourcePaths(id);
                    for (var entry : source.files().entrySet()) retained.put(entry.getValue().relativePath(), sourcePaths.get(entry.getKey()));
                    repository.saveJob(batch.batchId(), id, source.relativeRoot());
                }
                // Ancillary originals and OS metadata are retained but excluded from source identity.
                for (var file : batch.files()) if (!retained.containsKey(file.relativePath())) {
                    Path extraRoot = store.root().resolve("batches").resolve(batch.batchId().toString());
                    if (!newlyRetained.contains(extraRoot)) {
                        try { store.safeDirectory(extraRoot); } catch (IOException e) { throw new UncheckedIOException(e); }
                        newlyRetained.add(extraRoot);
                    }
                    Path target = extraRoot.resolve(file.relativePath()); move(file.path(), target);
                    retained.put(file.relativePath(), store.root().relativize(target).toString().replace('\\', '/'));
                }
                repository.saveBatchFiles(batch, retained);
                repository.saveIdempotency(idempotencyKey, hash, batch.batchId());
                return repository.get(batch.batchId());
            });
        } catch (RuntimeException e) {
            for (var path : newlyRetained) SourceStore.cleanup(path);
            throw e;
        } finally { SourceStore.cleanup(batch.stagingRoot()); }
    }
    private void move(Path source, Path target) {
        try { store.safeDirectory(target.getParent()); Files.move(source, target, StandardCopyOption.ATOMIC_MOVE); }
        catch (IOException e) { throw new UncheckedIOException("Cannot retain original bytes", e); }
    }
    public BatchView get(String id) {
        try { return repository.get(UUID.fromString(id)); }
        catch (IllegalArgumentException e) { throw IntakeException.invalid("Invalid batch id"); }
    }
}
