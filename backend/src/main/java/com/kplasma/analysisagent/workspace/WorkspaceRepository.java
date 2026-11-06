package com.kplasma.analysisagent.workspace;

import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.agent.AgentRequestRepository;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.ObjectMapper;

@Repository
public class WorkspaceRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final AgentRequestRepository agents;
    public WorkspaceRepository(JdbcTemplate jdbc,ObjectMapper mapper,AgentRequestRepository agents) {this.jdbc=jdbc;this.mapper=mapper;this.agents=agents;}
    public WorkspaceView lock() {
        return jdbc.queryForObject("select * from workspace where id=1 for update",(rs,n)->new WorkspaceView(new StateToken(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch"),rs.getLong("revision")),new Conversation(1,read(rs.getString("active_run"),RunRef.class),turns(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch")),rs.getString("agent_graph_version")),read(rs.getString("candidate_reference"),ReferenceState.class),agents.latest(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch"),false),agents.latest(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch"),true),agents.messages(rs.getLong("workspace_epoch"),rs.getLong("conversation_epoch")),conversations(rs.getLong("workspace_epoch"))));
    }
    private <T> T read(String json,Class<T> type) {return json==null?null:mapper.readValue(json,type);}
    private List<TurnSnapshot> turns(long workspace,long conversation) {
        return jdbc.query("select snapshot,ui from conversation_turn where workspace_id=1 and workspace_epoch=? and conversation_epoch=? order by ordinal",(rs,n)->{
            var turn=mapper.readValue(rs.getString(1),TurnSnapshot.class);
            return new TurnSnapshot(turn.id(),turn.askedAt(),turn.question(),turn.intent(),turn.context(),turn.answerRunRefs(),turn.answerSnapshot(),mapper.readValue(rs.getString(2),TurnUiSnapshot.class));
        },workspace,conversation);
    }
    public void append(TurnSnapshot turn) {
        var token=jdbc.queryForObject("select workspace_epoch,conversation_epoch,revision from workspace where id=1",(rs,n)->new StateToken(rs.getLong(1),rs.getLong(2),rs.getLong(3)));
        append(turn,token.workspaceEpoch(),token.conversationEpoch());
    }
    public void append(TurnSnapshot turn,long workspace,long conversation) {
        jdbc.update("insert into conversation_turn(id,workspace_id,workspace_epoch,conversation_epoch,snapshot,ui) values (?,1,?,?,?::jsonb,?::jsonb)",UUID.fromString(turn.id()),workspace,conversation,mapper.writeValueAsString(turn),mapper.writeValueAsString(turn.ui()));
    }
    public boolean hasTurn(UUID id) {return Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from conversation_turn where id=?)",Boolean.class,id));}
    public void updateUi(UUID id,TurnUiSnapshot ui) {jdbc.update("update conversation_turn set ui=?::jsonb where id=?",mapper.writeValueAsString(ui),id);}
    public void references(ReferenceState candidate,RunRef active) {jdbc.update("update workspace set active_run=?::jsonb,candidate_reference=?::jsonb where id=1",mapper.writeValueAsString(active),mapper.writeValueAsString(candidate));}
    public void invalidateAgentReferences(StateToken token){agents.invalidateReferences(token.workspaceEpoch(),token.conversationEpoch());}
    public void advance() {
        jdbc.update("update workspace set revision=revision+1 where id=1");
        jdbc.update("update workspace_conversation c set updated_at=now() from workspace w where w.id=1 and c.workspace_epoch=w.workspace_epoch and c.conversation_epoch=w.conversation_epoch");
    }
    public void advance(long workspace,long conversation) {
        jdbc.update("update workspace set revision=revision+1 where id=1 and workspace_epoch=? and conversation_epoch=?",workspace,conversation);
        jdbc.update("update workspace_conversation set updated_at=now() where workspace_epoch=? and conversation_epoch=?",workspace,conversation);
    }
    public boolean hasConversation(long workspace,long conversation) {
        return Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from workspace_conversation where workspace_epoch=? and conversation_epoch=?)",Boolean.class,workspace,conversation));
    }
    private List<ConversationSummary> conversations(long workspace) {
        return jdbc.query("""
            select c.conversation_epoch,c.created_at,c.updated_at,
                coalesce((select left(r.question,80) from agent_request r
                    where r.workspace_epoch=c.workspace_epoch and r.conversation_epoch=c.conversation_epoch
                    and r.question is not null order by r.created_at,r.id limit 1),
                    (select left(t.snapshot->>'question',80) from conversation_turn t
                    where t.workspace_epoch=c.workspace_epoch and t.conversation_epoch=c.conversation_epoch
                    order by t.ordinal limit 1),'새 대화') as title
            from workspace_conversation c where c.workspace_epoch=?
            order by c.updated_at desc,c.conversation_epoch desc
            """,(rs,n)->new ConversationSummary(rs.getLong("conversation_epoch"),rs.getString("title"),
                rs.getTimestamp("created_at").toInstant().toString(),rs.getTimestamp("updated_at").toInstant().toString()),workspace);
    }
    private void saveCurrentConversation() {
        jdbc.update("""
            update workspace_conversation c set active_run=w.active_run,candidate_reference=w.candidate_reference,
                agent_graph_version=w.agent_graph_version
            from workspace w where w.id=1 and c.workspace_epoch=w.workspace_epoch and c.conversation_epoch=w.conversation_epoch
            """);
    }
    public void newConversation(StateToken token) {
        saveCurrentConversation();
        long next=jdbc.queryForObject("select greatest(coalesce(max(conversation_epoch),0),?)+1 from workspace_conversation",Long.class,token.conversationEpoch());
        jdbc.update("insert into workspace_conversation(workspace_epoch,conversation_epoch) values (?,?)",token.workspaceEpoch(),next);
        jdbc.update("update workspace set conversation_epoch=?,active_run=null,candidate_reference=null,agent_graph_version=null,revision=revision+1 where id=1",next);
    }
    public void activateConversation(StateToken token,long conversation) {
        if(!hasConversation(token.workspaceEpoch(),conversation))throw new IntakeException("NOT_FOUND",404,"Conversation not found");
        if(token.conversationEpoch()==conversation)return;
        saveCurrentConversation();
        jdbc.update("""
            update workspace w set conversation_epoch=c.conversation_epoch,active_run=c.active_run,
                candidate_reference=c.candidate_reference,agent_graph_version=c.agent_graph_version,revision=w.revision+1
            from workspace_conversation c where w.id=1 and c.workspace_epoch=? and c.conversation_epoch=?
            """,token.workspaceEpoch(),conversation);
    }
    public void clear(boolean reset) {
        var token=jdbc.queryForObject("select workspace_epoch,conversation_epoch,revision from workspace where id=1",(rs,n)->new StateToken(rs.getLong(1),rs.getLong(2),rs.getLong(3)));
        if(!reset){newConversation(token);return;}
        agents.clearConversation(token.workspaceEpoch(),token.conversationEpoch(),true);
        jdbc.update("delete from conversation_turn where workspace_id=1");
        jdbc.update("delete from workspace_conversation");
        jdbc.update("delete from decision where workspace_id=1");
        jdbc.update("delete from workspace_idempotency");
        jdbc.update("update workspace set active_run=null,candidate_reference=null,agent_graph_version=null,conversation_epoch=conversation_epoch+1,workspace_epoch=workspace_epoch+1,revision=revision+1 where id=1");
        jdbc.update("insert into workspace_conversation(workspace_epoch,conversation_epoch) select workspace_epoch,conversation_epoch from workspace where id=1");
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
