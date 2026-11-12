package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.v2.V2ExecutionRepository;
import com.kplasma.analysisagent.agent.v3.V3CostPolicy;
import com.kplasma.analysisagent.agent.v3.V3Options;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.SnapshotValidator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Exercises the actual V3 result-save gate with artificial records and no DB/server. */
class AgentRequestServiceV3PolicyTest {
    private static final UUID REQUEST=UUID.fromString("00000000-0000-4000-8000-000000000010");
    private static final UUID EXECUTION=UUID.fromString("00000000-0000-4000-8000-000000000011");
    private static final RunRef RUN=new RunRef("RUN-ART-A","00000000-0000-4000-8000-000000000001");
    private final ObjectMapper mapper=new ObjectMapper();
    private final V2ExecutionRepository steps=mock(V2ExecutionRepository.class);
    private final AgentRequestRepository.Row row=mock(AgentRequestRepository.Row.class);
    private final AgentRequestService service=new AgentRequestService(
        new AgentRequestRepository(null,mapper,null),null,new SnapshotValidator(null,null),null,mapper,
        steps,null,null,null,null);

    private static Map<String,Object> m(Object... entries){
        var result=new LinkedHashMap<String,Object>();
        for(int i=0;i<entries.length;i+=2)result.put((String)entries[i],entries[i+1]);
        return result;
    }
    private static Map<String,Object> ref(){return m("runId",RUN.runId(),"runVersionId",RUN.runVersionId());}
    private Map<String,Object> output(String action,String policy){
        var record=m("reviewId","ART-POLICY-1","targetRunId",RUN.runId(),"targetRunRef",ref(),
            "decision","REJECT","comment","비용 초과를 두 번 적었지만 하나의 심사에서 반려했다.",
            "createdAt","2026-01-01T00:00:00Z");
        var records=List.of(record);
        when(row.id()).thenReturn(REQUEST);
        when(row.v3Options()).thenReturn(V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",true)));
        when(row.manifest()).thenReturn(m("catalogRunRefs",List.of(ref()),"decisionRecords",records));
        when(steps.isToolStep(REQUEST,EXECUTION,"decision_records")).thenReturn(true);
        when(steps.savedStepInputs(REQUEST,EXECUTION)).thenReturn(mapper.valueToTree(
            m("action",action,"runs",List.of(ref()))));
        boolean cost="cost_exclusion".equals(action);
        var rules=cost?m("policy",policy,"action","APPLY_EXISTING_COST_RULE","threshold",1,
            "aggregationScope","ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY",
            "perRun",List.of(m("runId",RUN.runId(),"count",1,"status","비용 반려 1건","mixed",false,
                "costRejectionRecordIds",List.of("ART-POLICY-1"))),
            "excludedRunIds",List.of(RUN.runId()),"remainingRunIds",List.of(),"completeAggregation",true)
            :m("policy",policy,"action","DISABLED","threshold",null,"perRun",List.of(),
                "excludedRunIds",List.of(),"remainingRunIds",List.of(RUN.runId()),"completeAggregation",false);
        var retrieval=cost?m("totalInScope",1,"returned",0,"strategy","COMPLETE_RULE_AGGREGATION_WITH_PROOF")
            :m("totalInScope",1,"returned",0,"strategy","LOCAL_DENSE_LEXICAL_RECALL","model","ARTIFICIAL");
        var evidence=m("schemaVersion",1,"kind","decision_rag","status",cost?"ANSWERED":"NO_EVIDENCE",
            "synthetic",true,"answer","인공 기록 검토입니다.","scopeRunRefs",List.of(ref()),"citations",List.of(),
            "rules",rules,"retrieval",retrieval,"snapshotFingerprint",new V3DecisionEvidenceValidator(mapper).canonicalHash(records),
            "limitations",List.of("실제 데이터가 아닌 인공 계약 테스트입니다."));
        return m("candidates",cost?List.of():List.of(ref()),"decisionEvidence",evidence,"rules",rules,
            "retrieval",retrieval,"callCounts",m("rules",cost?1:0,"rag",cost?0:1));
    }
    private void validate(Map<String,Object> output){
        var body=new AgentRequestService.V2Write(1,0,null,null,1,"records",mapper.valueToTree(
            m("status","verified","runRefs",List.of(ref()),"outputs",output)));
        ReflectionTestUtils.invokeMethod(service,"validateV3Step",row,EXECUTION,body,List.of(RUN));
    }

    @Test void currentCostPolicyPassesTheActualV3StepSaveGateAndFullRecordValidation(){
        assertThatCode(()->validate(output("cost_exclusion",V3CostPolicy.VERSION))).doesNotThrowAnyException();
    }

    @Test void newlyExecutingCostStepsCannotUseHistoricalOrUnknownPolicyVersions(){
        for(String policy:List.of("cost-regex-1","cost-regex-unknown")){
            var output=output("cost_exclusion",policy);
            assertThatThrownBy(()->validate(output)).isInstanceOf(IntakeException.class)
                .hasMessageContaining("Unknown exclusion policy");
        }
    }

    @Test void semanticSearchStillUsesDisabledRulesAndCannotInjectTheCostPolicy(){
        assertThatCode(()->validate(output("search","disabled"))).doesNotThrowAnyException();
        var output=output("search",V3CostPolicy.VERSION);
        assertThatThrownBy(()->validate(output)).isInstanceOf(IntakeException.class)
            .hasMessageContaining("Semantic retrieval must not apply exclusion rules");
    }

    @Test void acceptedPolicyStillCannotForgeTheRemainingCandidateSet(){
        var output=output("cost_exclusion",V3CostPolicy.VERSION);
        output.put("candidates",List.of(ref()));
        assertThatThrownBy(()->validate(output)).isInstanceOf(IntakeException.class)
            .hasMessageContaining("candidate set differs");
    }
}
