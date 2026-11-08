package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

/** Public data only. Callers hold the request lock and commit events with their state changes. */
@Repository
public class AgentPublicEvents {
    private static final TypeReference<Map<String,Object>> MAP = new TypeReference<>() {};
    private static final Set<String> CODES = Set.of("QUEUED", "QUESTION_CHECK", "PLAN", "PLAN_VALIDATE", "PLAN_REVIEW",
        "FORWARD_LOOKUP", "REVERSE_SEARCH", "SEARCH_COMPLETE", "SEARCH_EMPTY", "COMPARE_RUNS",
        "COMPARE_OUTPUTS", "COMPARE_IEAD", "DERIVE", "RESULT_VALIDATE", "REUSE_RESULT", "NEEDS_RUNS",
        "NEEDS_BASELINE", "NEEDS_CONDITIONS", "RESUMED", "REPLAN", "GENERAL_ANSWER", "INTERPRET",
        "REVIEW", "REWRITE", "COMMIT", "RECOVERING");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public AgentPublicEvents(JdbcTemplate jdbc, ObjectMapper mapper) { this.jdbc=jdbc; this.mapper=mapper; }
    public record Write(long claimGeneration, long requestRevision, String eventKey, String type, Map<String,Object> payload) {}

    private static void check(boolean condition, String message) {
        if (!condition) throw new IntakeException("INVALID_PUBLIC_EVENT", 400, message);
    }
    private static void conflict(String message) { throw new IntakeException("PUBLIC_EVENT_CONFLICT", 409, message); }
    private String json(Object value) { return mapper.writeValueAsString(value); }
    private Map<String,Object> read(String value) { return mapper.readValue(value,MAP); }
    private static void identifier(Object value, String field) {
        check(value instanceof String s && s.matches("[A-Za-z0-9_.:-]{1,200}"), "Invalid "+field);
    }
    private static long number(Object value, String field, long minimum, long maximum) {
        check(value instanceof Number n && Double.isFinite(n.doubleValue()) && n.doubleValue()==n.longValue()
            && n.longValue()>=minimum && n.longValue()<=maximum, "Invalid "+field);
        return ((Number)value).longValue();
    }
    static Map<String,Object> validate(String type, Map<String,Object> raw) {
        check(type!=null && raw!=null, "Event type and payload are required");
        Map<String,Object> payload=new LinkedHashMap<>(raw);
        Set<String> allowed;
        switch(type) {
            case "activity" -> {
                allowed=Set.of("activityId","code","phase","stepId","runCount","metricIds");
                identifier(payload.get("activityId"),"activityId");
                check(CODES.contains(String.valueOf(payload.get("code"))),"Unknown activity code");
                check(Set.of("started","completed","reused").contains(String.valueOf(payload.get("phase"))),"Invalid activity phase");
                if(payload.containsKey("stepId")) identifier(payload.get("stepId"),"stepId");
                if(payload.containsKey("runCount")) number(payload.get("runCount"),"runCount",0,1_000_000);
                if(payload.containsKey("metricIds")) {
                    check(payload.get("metricIds") instanceof List<?> list && list.size()<=24,"Invalid metricIds");
                    for(Object item:(List<?>)payload.get("metricIds"))
                        check(item instanceof String s && s.matches("[A-Za-z][A-Za-z0-9_.]{0,79}"),"Invalid metric ID");
                }
            }
            case "answer.start" -> {
                allowed=Set.of("streamId","answerRevision","mode","rewrite");
                identifier(payload.get("streamId"),"streamId");
                check(Set.of("general","interpretation").contains(String.valueOf(payload.get("mode"))),"Invalid answer mode");
                if(payload.containsKey("answerRevision")) number(payload.get("answerRevision"),"answerRevision",1,1000);
                if(!payload.containsKey("rewrite")) payload.put("rewrite",false);
                check(payload.get("rewrite") instanceof Boolean,"Invalid rewrite flag");
            }
            case "answer.delta" -> {
                allowed=Set.of("streamId","answerRevision","blockId","text","chunkIndex");
                identifier(payload.get("streamId"),"streamId"); identifier(payload.get("blockId"),"blockId");
                number(payload.get("answerRevision"),"answerRevision",1,1000);
                number(payload.get("chunkIndex"),"chunkIndex",0,100_000);
                check(payload.get("text") instanceof String s && !s.isEmpty() && s.length()<=8192,"Invalid answer text size");
            }
            case "answer.reset" -> {
                allowed=Set.of("streamId","answerRevision","reason");
                identifier(payload.get("streamId"),"streamId");
                number(payload.get("answerRevision"),"answerRevision",1,1000);
                if(!payload.containsKey("reason")) payload.put("reason","RESET");
                check(payload.get("reason") instanceof String s && s.matches("[A-Z_]{1,80}"),"Invalid reset reason");
            }
            case "results.ready" -> {
                allowed=Set.of("executionIds");
                check(payload.get("executionIds") instanceof List<?> list && list.size()<=16,"Invalid executionIds");
                var ids=(List<?>)payload.get("executionIds");
                check(new HashSet<>(ids).size()==ids.size(),"Execution IDs must be unique");
                for(Object id:ids) {
                    check(id instanceof String,"Execution IDs must be strings");
                    try { UUID.fromString((String)id); } catch(IllegalArgumentException e) { check(false,"Invalid execution ID"); }
                }
            }
            default -> { throw new IntakeException("INVALID_PUBLIC_EVENT",400,"Worker cannot emit this event type"); }
        }
        check(allowed.containsAll(payload.keySet()),"Unknown public payload field");
        return payload;
    }

    public Map<String,Object> replay(UUID id, String key, String type, Map<String,Object> input) {
        var previous=jdbc.query("select *,input_payload=?::jsonb as same from agent_public_event where request_id=? and event_key=?",
            (rs,n)->{ if(!rs.getBoolean("same") || !type.equals(rs.getString("type")))
                throw new IntakeException("IDEMPOTENCY_CONFLICT",409,"Event key was already used with different content");
                return envelope(rs); },json(input),id,key);
        return previous.isEmpty()?null:previous.getFirst();
    }

    public Map<String,Object> worker(UUID id, Write body, Map<String,Object> payload) {
        check(body.eventKey()!=null && body.eventKey().length()<=200 && !body.eventKey().isBlank()
            && !body.eventKey().startsWith("system:"),"Invalid eventKey");
        var previous=replay(id,body.eventKey(),body.type(),payload);
        if(previous!=null) return previous;
        var input=new LinkedHashMap<>(payload);
        var current=jdbc.queryForMap("select public_answer_revision,public_stream_id,public_chunk_index,public_preview_chars,last_public_event_seq from agent_request where id=?",id);
        if(((Number)current.get("last_public_event_seq")).longValue()>=20_000) conflict("Public event limit reached");
        long revision=((Number)current.get("public_answer_revision")).longValue();
        if("answer.start".equals(body.type())) {
            long next=revision+1;
            if(payload.containsKey("answerRevision") && ((Number)payload.get("answerRevision")).longValue()!=next)
                conflict("Answer revisions must increase by one");
            payload.put("answerRevision",next);
            jdbc.update("update agent_request set public_answer_revision=?,public_stream_id=?,public_chunk_index=null where id=?",next,payload.get("streamId"),id);
        } else if("answer.delta".equals(body.type()) || "answer.reset".equals(body.type())) {
            if(!Objects.equals(current.get("public_stream_id"),payload.get("streamId"))
                || revision!=((Number)payload.get("answerRevision")).longValue()) conflict("Answer stream is no longer current");
            if("answer.delta".equals(body.type())) {
                long chunk=((Number)payload.get("chunkIndex")).longValue();
                Long last=current.get("public_chunk_index")==null?null:((Number)current.get("public_chunk_index")).longValue();
                if(last==null?chunk>1:chunk!=last+1) conflict("Answer chunks must be contiguous within a stream");
                int size=((String)payload.get("text")).length();
                if(((Number)current.get("public_preview_chars")).longValue()+size>1_000_000) conflict("Answer preview limit reached");
                jdbc.update("update agent_request set public_chunk_index=?,public_preview_chars=public_preview_chars+? where id=?",chunk,size,id);
            } else jdbc.update("update agent_request set public_stream_id=null,public_chunk_index=null where id=?",id);
        }
        return append(id,body.eventKey(),body.type(),payload,input);
    }

    private Map<String,Object> append(UUID id, String key, String type, Map<String,Object> payload, Map<String,Object> input) {
        long seq=jdbc.queryForObject("update agent_request set last_public_event_seq=last_public_event_seq+1 where id=? returning last_public_event_seq",Long.class,id);
        if("results.ready".equals(type)) payload.put("resultRevision",seq);
        return jdbc.queryForObject("""
            insert into agent_public_event(request_id,seq,event_key,request_revision,type,payload,input_payload)
            select id,?,?,request_revision,?,?::jsonb,?::jsonb from agent_request where id=? returning *
            """,(rs,n)->envelope(rs),seq,key,type,json(payload),json(input),id);
    }
    private Map<String,Object> envelope(ResultSet rs) throws SQLException {
        var scope=jdbc.queryForMap("select workspace_epoch,conversation_epoch from agent_request where id=?",rs.getObject("request_id",UUID.class));
        return envelope(rs,scope);
    }
    private Map<String,Object> envelope(ResultSet rs,Map<String,Object> scope) throws SQLException {
        Map<String,Object> event=new LinkedHashMap<>();
        event.put("schemaVersion",1); event.put("requestId",rs.getString("request_id"));
        event.put("workspaceEpoch",scope.get("workspace_epoch")); event.put("conversationEpoch",scope.get("conversation_epoch"));
        event.put("requestRevision",rs.getLong("request_revision")); event.put("seq",rs.getLong("seq"));
        event.put("occurredAt",rs.getTimestamp("occurred_at").toInstant().toString());
        event.put("type",rs.getString("type")); event.put("payload",read(rs.getString("payload"))); return event;
    }
    public List<Map<String,Object>> page(UUID id, long after, long through, int limit) {
        var scope=jdbc.queryForMap("select workspace_epoch,conversation_epoch from agent_request where id=?",id);
        return jdbc.query("select * from agent_public_event where request_id=? and seq>? and seq<=? order by seq limit ?",
            (rs,n)->envelope(rs,scope),id,after,through,limit);
    }
    public Map<String,Object> resultBinding(UUID id, long seq) {
        var values=jdbc.query("select payload::text from agent_public_event where request_id=? and seq=? and type='results.ready'",
            (rs,n)->read(rs.getString(1)),id,seq);
        if(values.isEmpty()) throw new IntakeException("NOT_FOUND",404,"Public result version not found");
        return values.getFirst();
    }

    public void running(UUID id, boolean recovering) {
        if(recovering) closeRunning(id,false);
        jdbc.update("update agent_request set running_started_at=case when running_duration_ms is not null then clock_timestamp() end where id=?",id);
        if(recovering) reset(id,"RECOVERY");
    }
    public void closeRunning(UUID id, boolean terminal) {
        jdbc.update("""
            update agent_request set running_duration_ms=case
                when running_duration_ms is null then null when running_started_at is null then running_duration_ms
                else running_duration_ms+greatest(0,floor(extract(epoch from
                    (least(clock_timestamp(),coalesce(lease_until,clock_timestamp()))-running_started_at))*1000)::bigint) end,
                running_started_at=null, execution_finished_at=case when ? then coalesce(execution_finished_at,clock_timestamp()) else execution_finished_at end
            where id=?
            """,terminal,id);
    }
    public void activity(UUID id,String code,String phase) {
        var row=jdbc.queryForMap("select request_revision,claim_generation from agent_request where id=?",id);
        String key="system:"+row.get("request_revision")+":"+row.get("claim_generation")+":"+code+":"+phase;
        boolean spansClaims=Set.of("QUEUED","RESUMED","NEEDS_RUNS","NEEDS_BASELINE","NEEDS_CONDITIONS").contains(code);
        String identity="system:"+row.get("request_revision")+":"+(spansClaims?"":row.get("claim_generation")+":")+code;
        var payload=new LinkedHashMap<String,Object>(Map.of("activityId",identity,"code",code,"phase",phase));
        if(replay(id,key,"activity",payload)==null) append(id,key,"activity",payload,payload);
    }
    public void reset(UUID id,String reason) {
        var row=jdbc.queryForMap("select public_stream_id,public_answer_revision,claim_generation,request_revision from agent_request where id=?",id);
        if(row.get("public_stream_id")==null) return;
        String key="system:"+row.get("request_revision")+":"+row.get("claim_generation")+":reset:"+reason;
        var payload=new LinkedHashMap<String,Object>(Map.of("streamId",row.get("public_stream_id"),"answerRevision",row.get("public_answer_revision"),"reason",reason));
        append(id,key,"answer.reset",payload,payload);
        jdbc.update("update agent_request set public_stream_id=null,public_chunk_index=null where id=?",id);
    }
    public void state(UUID id) {
        var row=jdbc.queryForMap("select status,stage,turn_id,running_duration_ms,execution_finished_at,request_revision,claim_generation from agent_request where id=?",id);
        Map<String,Object> payload=new LinkedHashMap<>(); payload.put("status",row.get("status"));payload.put("stage",row.get("stage"));payload.put("turnId",row.get("turn_id")==null?null:row.get("turn_id").toString());
        if(row.get("execution_finished_at")!=null && row.get("running_duration_ms")!=null) payload.put("durationMs",row.get("running_duration_ms"));
        String key="system:"+row.get("request_revision")+":"+row.get("claim_generation")+":state:"+row.get("status");
        if(replay(id,key,"request.state",payload)==null) append(id,key,"request.state",payload,payload);
    }
    public Map<String,Object> progress(UUID id,long through) {
        var projection=projection(id,through);
        Map<String,Object> value=new LinkedHashMap<>(); value.put("lastEventSeq",through);value.put("activities",projection.activities());
        value.put("answer",projection.answer());value.put("resultRevision",projection.resultRevision());return value;
    }
    public Map<String,Object> summary(UUID id,long through,Long duration,boolean finished) {
        if(!finished || duration==null) return null;
        return Map.of("durationMs",duration,"activities",projection(id,through).activities());
    }
    private Projection projection(UUID id,long through) {
        var projection=new Projection();
        jdbc.query("select type,payload::text,seq,occurred_at from agent_public_event where request_id=? and seq<=? order by seq",
            (org.springframework.jdbc.core.RowCallbackHandler)rs->projection.apply(rs.getString(1),read(rs.getString(2)),rs.getLong(3),rs.getTimestamp(4).toInstant().toString()),id,through);
        return projection;
    }
    static final class Projection {
        private final List<Map<String,Object>> activities=new ArrayList<>();
        private Map<String,Object> answer;
        private final LinkedHashMap<String,String> blocks=new LinkedHashMap<>();
        private Long resultRevision;
        void apply(String type,Map<String,Object> payload,long seq,String time) {
            switch(type) {
                case "activity" -> {
                    var activity=new LinkedHashMap<>(payload);activity.put("seq",seq);activity.put("occurredAt",time);activities.add(activity);
                    if(answer!=null && "started".equals(payload.get("phase"))) {
                        if("REVIEW".equals(payload.get("code"))) answer.put("status","reviewing");
                        if("REWRITE".equals(payload.get("code"))) answer.put("status","rewriting");
                    }
                }
                case "results.ready" -> resultRevision=((Number)payload.get("resultRevision")).longValue();
                case "answer.start" -> { blocks.clear();answer=new LinkedHashMap<>();
                    for(String key:List.of("streamId","answerRevision","mode")) answer.put(key,payload.get(key));
                    answer.put("status",Boolean.TRUE.equals(payload.get("rewrite"))?"rewriting":"writing"); }
                case "answer.delta" -> { if(matches(payload) && !"interrupted".equals(answer.get("status")))
                    blocks.merge((String)payload.get("blockId"),(String)payload.get("text"),String::concat); }
                case "answer.reset" -> { if(matches(payload)) { blocks.clear();answer.put("status","interrupted"); } }
                case "request.state" -> {
                    if(answer!=null && "COMPLETED".equals(payload.get("status"))) answer.put("status","done");
                    else if(answer!=null && Set.of("FAILED","CANCELLED").contains(String.valueOf(payload.get("status")))) {blocks.clear();answer.put("status","interrupted");}
                }
                default -> { }
            }
        }
        private boolean matches(Map<String,Object> payload) {
            return answer!=null && Objects.equals(answer.get("streamId"),payload.get("streamId"))
                && ((Number)answer.get("answerRevision")).longValue()==((Number)payload.get("answerRevision")).longValue();
        }
        List<Map<String,Object>> activities() { return activities; }
        Map<String,Object> answer() { if(answer==null)return null;var value=new LinkedHashMap<>(answer);
            value.put("blocks",blocks.entrySet().stream().map(e->Map.of("id",e.getKey(),"text",e.getValue())).toList());return value; }
        Long resultRevision() { return resultRevision; }
    }
}
