package com.kplasma.analysisagent.run;
import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
@Entity @Table(name="run_version")
public class RunVersionEntity {
    @Id UUID id;
    @Column(name="run_id") String runId;
    @Column(name="source_id") UUID sourceId;
    @Column(name="registered_at") Instant registeredAt;
    @JdbcTypeCode(SqlTypes.JSON) String summary;
    @Column(name="full_run") @JdbcTypeCode(SqlTypes.JSON) String fullRun;
    protected RunVersionEntity() {}
}
