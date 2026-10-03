package com.kplasma.analysisagent.ingestion;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.*;
import java.util.*;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Collect only managed originals with no database owner. Caller holds the intake lock. */
@Component
public class StorageGarbageCollector {
    private final JdbcTemplate jdbc;
    private final SourceStore store;

    public StorageGarbageCollector(JdbcTemplate jdbc, SourceStore store) {
        this.jdbc = jdbc;
        this.store = store;
    }

    /** A failed filesystem operation leaves an orphan that the same scan can retry after restart. */
    public boolean collect() {
        Path root = store.root();
        if (Files.isSymbolicLink(root)) return true;
        Set<Path> owned = new HashSet<>();
        for (String value : jdbc.queryForList("select storage_path from source_file union select storage_path from import_batch_file", String.class)) {
            Path path = root.resolve(value).normalize();
            if (!path.startsWith(root.resolve("sources")) && !path.startsWith(root.resolve("batches"))) continue;
            // Preserve every ancestor of an owned file, including paths reused by another batch.
            for (Path keep = path; keep != null && !keep.equals(root); keep = keep.getParent()) owned.add(keep);
        }
        boolean pending = false;
        for (String name : List.of("sources", "batches")) {
            Path directory = root.resolve(name);
            if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) continue;
            if (Files.isSymbolicLink(directory) || !Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) {
                pending = true;
                continue;
            }
            // Files.walk does not follow symlinks; unowned links themselves may be removed.
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                    if (path.equals(directory) || owned.contains(path)) continue;
                    try { Files.deleteIfExists(path); }
                    catch (IOException | SecurityException failure) { pending = true; }
                }
            } catch (IOException | UncheckedIOException | SecurityException failure) { pending = true; }
        }
        if (pending) LoggerFactory.getLogger(StorageGarbageCollector.class).warn("Managed original cleanup remains pending; startup recovery will retry");
        return pending;
    }
}
