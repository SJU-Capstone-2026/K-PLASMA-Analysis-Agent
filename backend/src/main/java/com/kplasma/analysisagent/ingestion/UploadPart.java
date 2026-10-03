package com.kplasma.analysisagent.ingestion;
import java.nio.file.Path;
/** Owned temporary upload. The byte hint is informational; validation always reads actual bytes. */
public record UploadPart(String partName, Path path, long bytes) {}
