package com.kplasma.analysisagent.workspace;

import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.ObjectMapper;

@Repository
public class WorkspaceRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    public WorkspaceRepository(JdbcTemplate jdbc,ObjectMapper mapper) {this.jdbc=jdbc;this.mapper=mapper;}
    public WorkspaceView lock() {
        return jdbc.queryForObject("select * from workspace where id=1 for update",(rs,n)->new WorkspaceView(new StateToken(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch"),rs.getLong("revision")),new Conversation(1,read(rs.getString("active_run"),RunRef.class),turns()),read(rs.getString("candidate_reference"),ReferenceState.class)));
    }
    private <T> T read(String json,Class<T> type) {return json==null?null:mapper.readValue(json,type);}
    private List<TurnSnapshot> turns() {
        return jdbc.query("select snapshot,ui from conversation_turn where workspace_id=1 order by ordinal",(rs,n)->{
            var turn=mapper.readValue(rs.getString(1),TurnSnapshot.class);
            return new TurnSnapshot(turn.id(),turn.askedAt(),turn.question(),turn.intent(),turn.context(),turn.answerRunRefs(),turn.answerSnapshot(),mapper.readValue(rs.getString(2),TurnUiSnapshot.class));
        });
    }
    public void append(TurnSnapshot turn) {
        jdbc.update("insert into conversation_turn(id,workspace_id,snapshot,ui) values (?,1,?::jsonb,?::jsonb)",UUID.fromString(turn.id()),mapper.writeValueAsString(turn),mapper.writeValueAsString(turn.ui()));
    }
    public boolean hasTurn(UUID id) {return Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from conversation_turn where id=?)",Boolean.class,id));}
    public void updateUi(UUID id,TurnUiSnapshot ui) {jdbc.update("update conversation_turn set ui=?::jsonb where id=?",mapper.writeValueAsString(ui),id);}
    public void references(ReferenceState candidate,RunRef active) {jdbc.update("update workspace set active_run=?::jsonb,candidate_reference=?::jsonb where id=1",mapper.writeValueAsString(active),mapper.writeValueAsString(candidate));}
    public void advance() {jdbc.update("update workspace set revision=revision+1 where id=1");}
    public void clear(boolean reset) {
        jdbc.update("delete from conversation_turn where workspace_id=1");
        if(reset)jdbc.update("delete from decision where workspace_id=1");
        jdbc.update("update workspace set active_run=null,candidate_reference=null,conversation_epoch=conversation_epoch+1,workspace_epoch=workspace_epoch+?,revision=revision+1 where id=1",reset?1:0);
    }
    public String replay(long workspace,long conversation,String scope,String key,Object payload) {
        var rows=jdbc.query("select result_id,payload=?::jsonb as same from workspace_idempotency where workspace_epoch=? and conversation_epoch=? and scope=? and idempotency_key=?",(rs,n)->{
            if(!rs.getBoolean("same"))throw new IntakeException("IDEMPOTENCY_CONFLICT",409,"Idempotency key was already used for a different request");
            return rs.getString("result_id");
        },mapper.writeValueAsString(payload),workspace,conversation,scope,key);
        return rows.isEmpty()?null:rows.getFirst();
    }
    public void remember(long workspace,long conversation,String scope,String key,Object payload,String result) {
        jdbc.update("insert into workspace_idempotency(workspace_epoch,conversation_epoch,scope,idempotency_key,payload,result_id) values (?,?,?,?,?::jsonb,?)",workspace,conversation,scope,key,mapper.writeValueAsString(payload),result);
    }
}
