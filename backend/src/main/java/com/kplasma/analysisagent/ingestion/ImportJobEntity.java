package com.kplasma.analysisagent.ingestion;
import jakarta.persistence.*;
import java.util.UUID;
@Entity @Table(name = "import_job")
public class ImportJobEntity {
    @Id UUID id;
    @Column(name="batch_id") UUID batchId;
    @Column(name="source_id") UUID sourceId;
    @Column(name="source_root") String sourceRoot;
    @Column(name="run_id") String runId;
    @Column(name="run_version_id") UUID runVersionId;
    String status;
    String reason;
    protected ImportJobEntity() {}
}
