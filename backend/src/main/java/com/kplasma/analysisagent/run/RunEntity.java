package com.kplasma.analysisagent.run;
import jakarta.persistence.*;
import java.util.UUID;
@Entity @Table(name="run")
public class RunEntity {
    @Id @Column(name="run_id") String runId;
    @Column(name="current_version_id") UUID currentVersionId;
    protected RunEntity() {}
}
