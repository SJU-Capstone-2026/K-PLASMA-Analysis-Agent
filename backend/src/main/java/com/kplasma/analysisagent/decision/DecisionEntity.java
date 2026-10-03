package com.kplasma.analysisagent.decision;
import jakarta.persistence.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
@Entity @Table(name="decision")
public class DecisionEntity {
    @Id @Column(name="review_id") String reviewId;
    @Column(name="workspace_id") Integer workspaceId;
    long ordinal;
    @JdbcTypeCode(SqlTypes.JSON) String record;
    protected DecisionEntity() {}
}
