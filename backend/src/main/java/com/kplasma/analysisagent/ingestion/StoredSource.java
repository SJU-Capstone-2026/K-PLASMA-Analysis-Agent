package com.kplasma.analysisagent.ingestion;
import java.util.Map;
import java.util.UUID;
/** Original Run-relative files, with upload-root lineage retained separately. */
public record StoredSource(UUID sourceId, String relativeRoot, Map<String, StoredBatch.File> files, String sha256) {
    public StoredSource { files = Map.copyOf(files); }
}
