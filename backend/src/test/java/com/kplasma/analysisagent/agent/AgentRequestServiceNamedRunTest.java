package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.v2.V2ExecutionRepository;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.test.util.ReflectionTestUtils;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentRequestServiceNamedRunTest {
    private static final RunRef A=new RunRef("RUN-ART-A","00000000-0000-4000-8000-000000000001");
    private static final RunRef B=new RunRef("RUN-ART-B","00000000-0000-4000-8000-000000000002");
    private final ObjectMapper mapper=new ObjectMapper();
    private final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    private final WorkspaceRepository workspace=mock(WorkspaceRepository.class);
    private final AgentRequestRepository requests=mock(AgentRequestRepository.class);
    private final AgentRequestService service=new AgentRequestService(requests,workspace,new SnapshotValidator(null,jdbc),jdbc,mapper,
        mock(V2ExecutionRepository.class),mock(AgentPublicEvents.class),null,null,null);
    private Map<String,Object> ref(RunRef r){return Map.of("runId",r.runId(),"runVersionId",r.runVersionId());}
    private AgentRequestRepository.Row row(String version,Map<String,Object> context) {
        var row=mock(AgentRequestRepository.Row.class);
        when(row.graphVersion()).thenReturn(version);when(row.context()).thenReturn(context);return row;
    }
    @SuppressWarnings("unchecked") private Set<RunRef> direct(String version,Map<String,Object> context){
        return ReflectionTestUtils.invokeMethod(service,"directContextRefs",row(version,context));
    }
    @Test void namedRunDoesNotAuthorizeAnUnrelatedOldActiveOrCandidateRun() {
        var context=Map.<String,Object>of("activeRun",ref(A),"candidateReferences",List.of(ref(A)),
            "namedRunReferences",List.of(ref(B)),"unresolvedRunNames",List.of());
        assertThat(direct("v3",context)).containsExactly(B);
    }
    @Test void currentRequestAttachmentsAndNamedRunsAreBothAuthorizedWithoutChangingEitherScope() {
        var attached=Map.of("entries",List.of(Map.of("key","R1","ref",ref(A))));
        var context=Map.<String,Object>of("comparisonReference",attached,"namedRunReferences",List.of(ref(B)),"unresolvedRunNames",List.of());
        assertThat(direct("v3",context)).containsExactlyInAnyOrder(A,B);
        assertThat(context.get("comparisonReference")).isSameAs(attached);
    }
    @Test void unresolvedNamesRejectEvenAPartialKnownOrOldScope() {
        var context=Map.<String,Object>of("activeRun",ref(A),"namedRunReferences",List.of(ref(B)),
            "unresolvedRunNames",List.of("RUN-ART-UNKNOWN"));
        assertThatThrownBy(()->direct("v3",context)).isInstanceOf(IntakeException.class).hasMessageContaining("Named Runs could not be resolved");
    }
    @Test void theNormalUnnamedAttachmentAndActiveRunPathIsPreserved() {
        assertThat(direct("v3",Map.of("activeRun",ref(A),"namedRunReferences",List.of(),"unresolvedRunNames",List.of())))
            .containsExactly(A);
    }
    @SuppressWarnings({"unchecked","rawtypes"}) private tools.jackson.databind.JsonNode submit(String version) {
        var token=new StateToken(1,1,1);
        when(workspace.lock()).thenReturn(new WorkspaceView(token,new Conversation(1,null,List.of(),null),null));
        when(requests.latest(anyLong(),anyLong(),anyBoolean())).thenReturn(null);
        when(requests.json(any())).thenAnswer(call->mapper.writeValueAsString(call.getArgument(0)));
        when(requests.view(nullable(AgentRequestRepository.Row.class))).thenReturn(Map.of());
        doReturn(List.of(B)).when(jdbc).query(startsWith("select r.run_id,v.id::text"),any(RowMapper.class),any(Object[].class));
        var options="v3".equals(version)?Map.<String,Object>of("rulesEnabled",true,"ragEnabled",true):null;
        String question=B.runId()+" 의 과거 판단 기록 보여줘";
        var body=new AgentRequestService.Submission(question,token,null,null,null,List.of(),List.of(),version,options);
        service.submit(body,"artificial-name-"+version);
        var captured=ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(startsWith("insert into agent_request"),any(UUID.class),eq(1L),eq(1L),eq(question),anyString(),captured.capture(),eq(version),nullable(String.class));
        return mapper.readTree(captured.getValue());
    }
    @Test void actualV3SubmissionPinsNamesWithoutPretendingTheyWereUiAttachments() {
        var context=submit("v3");
        assertThat(context.path("namedRunReferences").size()).isEqualTo(1);
        assertThat(context.path("namedRunReferences").get(0).path("runId").asString()).isEqualTo(B.runId());
        assertThat(context.path("comparisonReference").path("entries").size()).isZero();
        assertThat(context.path("activeRun").isNull()).isTrue();
        assertThat(context.path("namedRunBindings").get(0).path("source").path("quote").asString()).isEqualTo(B.runId());
    }
    @Test void v1SubmissionDoesNotGainNamedRunResolutionOrTheCatalogIdentityQuery() {
        var context=submit("v1");
        assertThat(context.has("namedRunReferences")).isFalse();
        verify(jdbc,never()).query(anyString(),any(RowMapper.class),any(Object[].class));
    }
    @Test void v2SubmissionDoesNotGainNamedRunResolutionOrTheCatalogIdentityQuery() {
        var context=submit("v2");
        assertThat(context.has("namedRunReferences")).isFalse();
        verify(jdbc,never()).query(anyString(),any(RowMapper.class),any(Object[].class));
    }
}
