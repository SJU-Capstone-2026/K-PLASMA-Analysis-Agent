package com.kplasma.analysisagent.ingestion;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;
public record StoredBatch(UUID batchId, Path stagingRoot, List<File> files, long totalBytes, long receivedBytes) {
    public StoredBatch { files = List.copyOf(files); }
    public record File(String relativePath, Path path, long size, String sha256, String kind) {}
}
