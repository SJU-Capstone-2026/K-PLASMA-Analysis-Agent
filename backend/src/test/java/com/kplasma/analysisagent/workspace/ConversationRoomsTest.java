package com.kplasma.analysisagent.workspace;

import java.util.Map;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class ConversationRoomsTest extends WorkspaceTestSupport {
    @Test void roomsRestoreExactTurnsUiReferencesAndGraphVersion() throws Exception {
        long first=token().get("conversationEpoch").longValue();
        var original=turn();
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",original),"original-turn");
        ok("PUT","/api/workspace/reference",Map.of("stateToken",token(),"activeRun",refs.get(0),
            "candidateReference",Map.of("kind","후보 집합","runs",refs.subList(0,2))),null);
        ok("PATCH","/api/workspace/turns/"+original.get("id").stringValue()+"/ui",
            Map.of("stateToken",token(),"ui",Map.of("collapsed",true,"runDetailTabs",Map.of("SYNTHETIC-1","iad"))),null);
        jdbc.update("update workspace set agent_graph_version='v2' where id=1");
        var before=state();
        var fresh=ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        long second=fresh.get("stateToken").get("conversationEpoch").longValue();
        assertThat(fresh.get("conversations").size()).isEqualTo(2);
        assertThat(fresh.get("conversation").get("turns").size()).isZero();
        assertThat(fresh.get("candidateReference").isNull()).isTrue();
        assertThat(fresh.get("conversation").get("agentGraphVersion").isNull()).isTrue();
        var other=turn();other.put("question","다른 방의 질문");
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",other),"other-turn");
        ok("PUT","/api/workspace/reference",Map.of("stateToken",token(),"activeRun",refs.get(2),
            "candidateReference",Map.of("kind","단일 Run","runs",List.of(refs.get(2)))),null);
        var secondState=state();
        var restored=ok("POST","/api/workspace/conversations/"+first+"/activate",Map.of("stateToken",token()),null);
        assertThat(restored.get("conversation")).isEqualTo(before.get("conversation"));
        assertThat(restored.get("candidateReference")).isEqualTo(before.get("candidateReference"));
        assertThat(state()).isEqualTo(restored);
        var stale=token();
        var again=ok("POST","/api/workspace/conversations/"+second+"/activate",Map.of("stateToken",token()),null);
        assertThat(again.get("conversation")).isEqualTo(secondState.get("conversation"));
        assertThat(again.get("candidateReference")).isEqualTo(secondState.get("candidateReference"));
        rejects("PUT","/api/workspace/reference",Map.of("stateToken",stale,"activeRun",refs.get(0),
            "candidateReference",Map.of("kind","단일 Run","runs",List.of(refs.get(0)))),null,409,"STALE_CONTEXT");
        rejects("POST","/api/workspace/conversations/999999/activate",Map.of("stateToken",token()),null,404,"NOT_FOUND");
        assertThat(state()).isEqualTo(again);
        ok("POST","/api/workspace/conversations/"+first+"/activate",Map.of("stateToken",token()),null);
        var third=ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        assertThat(third.get("stateToken").get("conversationEpoch").longValue()).isGreaterThan(second);
        assertThat(third.get("conversations").size()).isEqualTo(3);
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-2")),null);
        var deleted=ok("POST","/api/workspace/conversations/"+second+"/activate",Map.of("stateToken",token()),null);
        assertThat(deleted.get("candidateReference").isNull()).isTrue();
        assertThat(deleted.get("conversation").get("activeRun").isNull()).isTrue();
        assertThat(deleted.get("conversation").get("turns")).isEqualTo(secondState.get("conversation").get("turns"));
        var reset=ok("POST","/api/workspace/reset",Map.of("stateToken",token()),null);
        assertThat(reset.get("conversations").size()).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from conversation_turn",Long.class)).isZero();
        rejects("POST","/api/workspace/conversations/"+first+"/activate",Map.of("stateToken",token()),null,404,"NOT_FOUND");
    }
}
