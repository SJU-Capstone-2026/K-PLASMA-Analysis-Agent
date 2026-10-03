package com.kplasma.analysisagent.decision;
import com.kplasma.analysisagent.contract.WorkspaceDto.DecisionRecord;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.ObjectMapper;
@Repository
public class DecisionRepository {
    private final JdbcTemplate jdbc;private final ObjectMapper mapper;
    public DecisionRepository(JdbcTemplate jdbc,ObjectMapper mapper){this.jdbc=jdbc;this.mapper=mapper;}
    public List<DecisionRecord> list(){return jdbc.query("select record from decision where workspace_id=1 order by ordinal desc",(rs,n)->mapper.readValue(rs.getString(1),DecisionRecord.class));}
    public DecisionRecord get(String id){return jdbc.queryForObject("select record from decision where review_id=?",(rs,n)->mapper.readValue(rs.getString(1),DecisionRecord.class),id);}
    public void save(DecisionRecord record){if(Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from decision where review_id=?)",Boolean.class,record.reviewId())))throw new IntakeException("DECISION_EXISTS",409,"Decision id already exists");jdbc.update("insert into decision(review_id,workspace_id,record) values (?,1,?::jsonb)",record.reviewId(),mapper.writeValueAsString(record));}
}
