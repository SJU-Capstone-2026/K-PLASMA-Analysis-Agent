package com.kplasma.analysisagent.workspace;
import jakarta.persistence.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
@Entity @Table(name="workspace")
public class WorkspaceEntity {
    @Id Integer id;
    @Column(name="workspace_epoch") long workspaceEpoch;
    @Column(name="conversation_epoch") long conversationEpoch;
    long revision;
    @Column(name="active_run") @JdbcTypeCode(SqlTypes.JSON) String activeRun;
    @Column(name="candidate_reference") @JdbcTypeCode(SqlTypes.JSON) String candidateReference;
    protected WorkspaceEntity() {}
}
