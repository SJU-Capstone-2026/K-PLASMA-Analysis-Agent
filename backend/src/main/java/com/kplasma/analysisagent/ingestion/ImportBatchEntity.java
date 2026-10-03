package com.kplasma.analysisagent.ingestion;
import jakarta.persistence.*;
import java.util.UUID;
@Entity @Table(name = "import_batch")
public class ImportBatchEntity {
    @Id UUID id;
    String status;
    @Column(name="received_bytes") long receivedBytes;
    @Column(name="total_bytes") long totalBytes;
    @Column(name="processed_runs") int processedRuns;
    @Column(name="total_runs") int totalRuns;
    protected ImportBatchEntity() {}
}
