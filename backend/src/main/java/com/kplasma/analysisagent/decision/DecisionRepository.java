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
    /** Stored JSON in save order, for the Agent's deterministic reuse rules. */
    public List<String> recordsInSaveOrder(String graphVersion){return jdbc.queryForList("select record::text from decision where workspace_id=1 and (? or origin_graph_version in ('v1','v2','v3')) order by ordinal",String.class,"v2_localLLM".equals(graphVersion));}
    public boolean cloudRecordsAllowed(List<?> records){
        if(records.isEmpty())return true;
        Set<String> ids=new HashSet<>();
        for(Object value:records){
            if(!(value instanceof Map<?,?> record)||!(record.get("reviewId") instanceof String id))return false;
            ids.add(id);
        }
        var allowed=jdbc.queryForList("select review_id from decision where workspace_id=1 and origin_graph_version in ('v1','v2','v3')",String.class);
        return new HashSet<>(allowed).containsAll(ids);
    }
    public DecisionRecord get(String id){return jdbc.queryForObject("select record from decision where review_id=?",(rs,n)->mapper.readValue(rs.getString(1),DecisionRecord.class),id);}
    public void save(DecisionRecord record,String graphVersion){if(Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from decision where review_id=?)",Boolean.class,record.reviewId())))throw new IntakeException("DECISION_EXISTS",409,"Decision id already exists");jdbc.update("insert into decision(review_id,workspace_id,record,origin_graph_version) values (?,1,?::jsonb,?)",record.reviewId(),mapper.writeValueAsString(record),graphVersion);}
}
