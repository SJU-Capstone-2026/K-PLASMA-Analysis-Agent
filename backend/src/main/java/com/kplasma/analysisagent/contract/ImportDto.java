package com.kplasma.analysisagent.contract;

import java.util.List;
import java.util.Map;

/** Upload manifests expose relative paths; storage locations never cross the HTTP boundary. */
public final class ImportDto {
    private ImportDto() {}
    public record ManifestFile(String path, String kind, long size, String sha256) {}
    public record UploadEntry(String partName, String relativePath) {}
    /** Intake names parts and paths only; server-produced ManifestFile is separate. */
    public record UploadManifest(String mode, List<UploadEntry> entries) {}
    public record JobView(String jobId, String runId, String runVersionId, String status,
            String reason, List<WorkspaceDto.Error> errors) {}
    public record BatchView(String batchId, String status, long receivedBytes, long totalBytes,
            int processedRuns, int totalRuns, List<JobView> jobs) {}
    public record CatalogView(List<RunDto.Summary> runs, List<JobView> jobs,
            Map<String, List<RunDto.SourceFile>> sourceFilesByVersion) {}
}
