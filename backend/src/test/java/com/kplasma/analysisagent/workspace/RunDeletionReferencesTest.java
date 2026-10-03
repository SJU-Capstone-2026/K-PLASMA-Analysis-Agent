package com.kplasma.analysisagent.workspace;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class RunDeletionReferencesTest extends WorkspaceTestSupport {
    // Catches dropping an old version still used by a turn, and partially applying a blocked bulk delete.
    @Test void conversationReferenceBlocksEntireSelection() throws Exception {
        ok("POST","/api/workspace/turns",Map.of("stateToken",token(),"turn",turn()),"turn");
        var before=state();
        rejects("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0","SYNTHETIC-3")),null,409,"RUN_IN_USE");
        assertThat(state()).isEqualTo(before);assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(4);
        var result=send("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(json(result).get("message").stringValue()).contains("SYNTHETIC-0","대화");
    }
    @Test void storedDecisionBlocksDeletionAcrossNewConversations() throws Exception {
        ok("POST","/api/decisions",write(review()),"decision");
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),null);
        var result=send("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(result.statusCode()).isEqualTo(409);assertThat(json(result).get("message").stringValue()).contains("판단","SYNTHETIC-0");
        assertThat(ok("GET","/api/decisions",null,null).size()).isEqualTo(1);
    }
    @Test void activeRunAndCandidateReferenceBlockUntilExplicitlyReleased() throws Exception {
        var body=new HashMap<String,Object>();body.put("stateToken",token());body.put("activeRun",refs.get(0));body.put("candidateReference",Map.of("kind","후보 집합","runs",List.of(refs.get(1))));
        ok("PUT","/api/workspace/reference",body,null);
        for(String id:List.of("SYNTHETIC-0","SYNTHETIC-1"))rejects("POST","/api/runs/delete",Map.of("runIds",List.of(id)),null,409,"RUN_IN_USE");
        body.put("stateToken",token());body.put("activeRun",null);body.put("candidateReference",null);ok("PUT","/api/workspace/reference",body,null);
        assertThat(ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0","SYNTHETIC-1")),null).get("deletedRunIds").size()).isEqualTo(2);
    }
}
