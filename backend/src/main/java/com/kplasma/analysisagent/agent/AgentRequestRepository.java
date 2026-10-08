package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Repository
public class AgentRequestRepository {
    private static final TypeReference<Map<String,Object>> MAP=new TypeReference<>() {};
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    public AgentRequestRepository(JdbcTemplate jdbc,ObjectMapper mapper){this.jdbc=jdbc;this.mapper=mapper;}
    public record Row(UUID id,long workspaceEpoch,long conversationEpoch,long revision,long generation,
        String status,String stage,String question,Map<String,Object> context,Map<String,Object> manifest,
        Map<String,Object> pending,Map<String,Object> error,Map<String,Object> partial,Map<String,Object> answer,
        String turnId,Instant createdAt,Instant leaseUntil,boolean dependsOnContext,String operationKind,Map<String,Object> attempts) {}
    private Row row(ResultSet rs,int index) throws SQLException {
        var lease=rs.getTimestamp("lease_until");
        return new Row(rs.getObject("id",UUID.class),rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch"),
            rs.getLong("request_revision"),rs.getLong("claim_generation"),rs.getString("status"),rs.getString("stage"),rs.getString("question"),
            read(rs.getString("context_snapshot")),read(rs.getString("manifest")),read(rs.getString("pending_input")),read(rs.getString("error")),
            read(rs.getString("partial_result")),read(rs.getString("final_answer")),rs.getString("turn_id"),rs.getTimestamp("created_at").toInstant(),
            lease==null?null:lease.toInstant(),rs.getBoolean("depends_on_context"),rs.getString("operation_kind"),read(rs.getString("attempts")));
    }
    public Map<String,Object> read(String value){return value==null?null:mapper.readValue(value,MAP);}
    public String json(Object value){return mapper.writeValueAsString(value);}
    public Row get(UUID id,boolean lock){var rows=jdbc.query("select * from agent_request where id=?"+(lock?" for update":""),this::row,id);if(rows.isEmpty())throw new IntakeException("NOT_FOUND",404,"Agent request not found");return rows.getFirst();}
    public Map<String,Object> view(Row row) {
        Map<String,Object> value=new LinkedHashMap<>();value.put("requestId",row.id().toString());value.put("requestRevision",row.revision());
        value.put("status",row.status());value.put("stage",row.stage());value.put("graphVersion","v1");value.put("question",row.question());
        value.put("pendingInput",row.pending());value.put("error",row.error());value.put("partialResult",row.partial());value.put("turnId",row.turnId());
        value.put("answerSnapshot",row.answer()==null?null:row.answer().get("answerSnapshot"));value.put("intent",row.answer()==null?null:row.answer().get("intent"));
        value.put("usedRunRefs",row.answer()==null?List.of():row.answer().getOrDefault("usedRunRefs",List.of()));value.put("inputEvents",events(row.id()));
        value.put("createdAt",row.createdAt().toString());return value;
    }
    public List<Map<String,Object>> events(UUID id){return jdbc.query("select * from agent_input_event where request_id=? order by request_revision",(rs,n)->{
        Map<String,Object> item=new LinkedHashMap<>();item.put("id",rs.getString("id"));item.put("requestRevision",rs.getLong("request_revision"));
        item.put("input",read(rs.getString("input")));item.put("createdAt",rs.getTimestamp("created_at").toInstant().toString());return item;
    },id);}
    public Map<String,Object> latest(long workspace,long conversation,boolean failed){var rows=jdbc.query("select * from agent_request where workspace_epoch=? and conversation_epoch=? and "+(failed?"true":"status in ('QUEUED','RUNNING','NEEDS_INPUT')")+" order by created_at desc limit 1",this::row,workspace,conversation);return rows.isEmpty()||(failed&&!"FAILED".equals(rows.getFirst().status()))?null:view(rows.getFirst());}
    public void purgeTransient(UUID id){jdbc.update("delete from agent_checkpoint where request_id=?",id);jdbc.update("update agent_request set manifest=null where id=?",id);}
    public void cancel(UUID id,String code){jdbc.update("update agent_request set status='CANCELLED',stage='cancelled',claim_generation=claim_generation+1,lease_until=null,pending_input=null,context_snapshot=null,partial_result=null,error=?::jsonb,updated_at=now() where id=? and status in ('QUEUED','RUNNING','NEEDS_INPUT')",json(Map.of("code",code,"message","요청의 문맥이 변경되거나 실행이 취소되었습니다.")),id);purgeTransient(id);}
    /** Caller holds workspace lock; cancelling rows precedes erasure so stale writers are fenced. */
    public void clearConversation(long workspace,long conversation,boolean reset){
        var ids=jdbc.queryForList("select id from agent_request where "+(reset?"workspace_epoch=?":"workspace_epoch=? and conversation_epoch=?")+" for update",UUID.class,reset?new Object[]{workspace}:new Object[]{workspace,conversation});
        for(UUID id:ids){cancel(id,"CONTEXT_CLEARED");jdbc.update("delete from agent_input_event where request_id=?",id);jdbc.update("update agent_request set status='CANCELLED',stage='cancelled',question=null,submission=null,context_snapshot=null,manifest=null,pending_input=null,error=null,partial_result=null,final_answer=null,attempts='{}'::jsonb where id=?",id);}
        jdbc.update("delete from workspace_idempotency where scope='AGENT' and workspace_epoch=?"+(reset?"":" and conversation_epoch=?"),reset?new Object[]{workspace}:new Object[]{workspace,conversation});
    }
    public void invalidateReferences(long workspace,long conversation){jdbc.queryForList("select id from agent_request where workspace_epoch=? and conversation_epoch=? and depends_on_context and status in ('QUEUED','RUNNING','NEEDS_INPUT') for update",UUID.class,workspace,conversation).forEach(id->invalidateContext(get(id,false),"REFERENCE_CHANGED"));}
    private boolean invalidateContext(Row row,String reason){
        if(row.operationKind()==null&&row.manifest()==null&&row.context()!=null){
            Map<String,Object> context=new LinkedHashMap<>(row.context());context.put("invalidationReason",reason);
            jdbc.update("update agent_request set context_snapshot=?::jsonb,updated_at=now() where id=?",json(context),row.id());return false;
        }
        cancel(row.id(),reason);return true;
    }
    public void invalidateRuns(Set<String> ids){
        var rows=jdbc.query("select * from agent_request where context_snapshot is not null or manifest is not null or partial_result is not null order by id for update",this::row);
        for(var row:rows) {
            if(Set.of("explain_concept","generate_answer").contains(String.valueOf(row.operationKind())))continue;
            Object dependency="compare_runs".equals(row.operationKind())&&row.context()!=null&&row.context().containsKey("comparisonReference")?row.context().get("comparisonReference"):row.context();
            if(containsRun(dependency,ids)||containsRun(row.manifest(),ids)||containsRun(row.partial(),ids)){
                if(invalidateContext(row,"RUN_DELETED"))jdbc.update("update agent_request set context_snapshot=null,partial_result=null where id=?",row.id());
            }
        }
    }
    private boolean containsRun(Object value,Set<String> ids){if(value instanceof Map<?,?> map){if(ids.contains(map.get("runId")))return true;return map.values().stream().anyMatch(v->containsRun(v,ids));}if(value instanceof List<?> list)return list.stream().anyMatch(v->containsRun(v,ids));return false;}
}
