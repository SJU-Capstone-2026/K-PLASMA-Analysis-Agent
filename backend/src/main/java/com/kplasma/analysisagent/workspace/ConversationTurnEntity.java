package com.kplasma.analysisagent.workspace;
import jakarta.persistence.*;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
@Entity @Table(name="conversation_turn")
public class ConversationTurnEntity {
    @Id UUID id;
    @Column(name="workspace_id") Integer workspaceId;
    long ordinal;
    @JdbcTypeCode(SqlTypes.JSON) String snapshot;
    @JdbcTypeCode(SqlTypes.JSON) String ui;
    protected ConversationTurnEntity() {}
}
