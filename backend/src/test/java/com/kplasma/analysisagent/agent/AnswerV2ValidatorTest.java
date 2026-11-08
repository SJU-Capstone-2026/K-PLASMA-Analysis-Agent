package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.contract.WorkspaceDto.AgentResponse;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.workspace.SnapshotValidator;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;

class AnswerV2ValidatorTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private final AnswerV2Validator validator=new AnswerV2Validator(new SnapshotValidator(null,null));
    @SuppressWarnings("unchecked") private Map<String,Object> wire(String key)throws Exception{
        return (Map<String,Object>)mapper.readValue(Files.readString(Path.of("../agent/tests/support/answer-v2-wire.json")),Map.class).get(key);
    }
    private AgentResponse response(Map<String,Object> snapshot){
        var result=(Map<?,?>)snapshot.get("result");
        @SuppressWarnings("unchecked") var refs=(List<Map<String,Object>>)snapshot.get("usedRunRefs");
        var inventory=refs.stream().map(r->mapper.convertValue(r,RunRef.class)).toList();
        return new AgentResponse(Map.of("compare_runs","RUN_COMPARISON","generate_answer","GENERAL_ANSWER","forward_lookup","FORWARD_LOOKUP","reverse_search","REVERSE_SEARCH").get(snapshot.get("kind")),String.valueOf(result.get("resultStatus")),List.of(),null,snapshot,inventory);
    }
    @Test void extendedFixtureIsStrictAndDoesNotWeakenHistoricalSchema()throws Exception{
        @SuppressWarnings("unchecked") var root=(Map<String,Object>)mapper.readValue(Files.readString(Path.of("../agent/tests/support/answer-v3-wire.json")),Map.class);
        @SuppressWarnings("unchecked") var snapshot=(Map<String,Object>)root.get("comparison");
        var extended=new AnswerV2Validator(new SnapshotValidator(null,null),true);
        extended.answer(response(snapshot),"인공 파형 비교");
        assertThatThrownBy(()->validator.answer(response(snapshot),"인공 파형 비교")).hasMessageContaining("Unknown answer version");
        @SuppressWarnings("unchecked") var result=(Map<String,Object>)snapshot.get("result");result.put("unexpected",true);
        assertThatThrownBy(()->extended.answer(response(snapshot),"인공 파형 비교")).hasMessageContaining("fields mismatch");
    }
    @Test void sharedFixturePreservesZeroNullAndCompletePartial()throws Exception{
        var comparison=wire("comparison");validator.answer(response(comparison),"인공 질문");
        var general=wire("general");validator.answer(response(general),(String)general.get("originalQuestion"));
        validator.comparison(wire("partial"),response(comparison).usedRunRefs(),true);
    }
    @Test void numericOnlyComparisonsAcceptNullAnswersAndKeepInventoryChecks()throws Exception{
        var extended=new AnswerV2Validator(new SnapshotValidator(null,null),true);
        for(int version:List.of(2,3)){
            @SuppressWarnings("unchecked") var root=(Map<String,Object>)mapper.readValue(Files.readString(Path.of("../agent/tests/support/answer-v"+version+"-wire.json")),Map.class);
            @SuppressWarnings("unchecked") var snapshot=(Map<String,Object>)root.get("comparison");
            snapshot.put("answer",null);
            var current=version==3?extended:validator;
            current.answer(response(snapshot),(String)snapshot.get("originalQuestion"));
            Collections.reverse((List<?>)snapshot.get("usedRunRefs"));
            assertThatThrownBy(()->current.answer(response(snapshot),(String)snapshot.get("originalQuestion"))).hasMessageContaining("inventory mismatch");
        }
    }
    @Test void missingScalarFieldsAndNonintegerSchemaFail()throws Exception{
        var snapshot=wire("comparison");snapshot.put("schemaVersion",2.5);
        assertThatThrownBy(()->validator.answer(response(snapshot),"인공 질문")).hasMessageContaining("Unknown answer version");
        snapshot.put("schemaVersion",2);var result=(Map<?,?>)snapshot.get("result");var run=(Map<?,?>)((List<?>)result.get("runs")).getFirst();
        var scalar=(Map<?,?>)((Map<?,?>)run.get("metrics")).get("ionFlux");scalar.remove("sourceValue");
        assertThatThrownBy(()->validator.answer(response(snapshot),"인공 질문")).hasMessageContaining("missing fields");
    }
    @Test void unknownObservationAndReorderedRefsFail()throws Exception{
        var snapshot=wire("comparison");
        @SuppressWarnings("unchecked") var answer=(Map<String,Object>)snapshot.get("answer");answer.put("observationIds",List.of("unknown"));
        assertThatThrownBy(()->validator.answer(response(snapshot),"인공 질문")).hasMessageContaining("Unknown answer observation");
        var second=wire("comparison");Collections.reverse((List<?>)second.get("usedRunRefs"));
        assertThatThrownBy(()->validator.answer(response(second),"인공 질문")).hasMessageContaining("inventory mismatch");
    }
    @Test void runConditionEvidenceIsCitableButCannotPretendToBeAnOutputSummary()throws Exception{
        var snapshot=wire("comparison");
        @SuppressWarnings("unchecked") var result=(Map<String,Object>)snapshot.get("result");
        @SuppressWarnings("unchecked") var observations=(List<Map<String,Object>>)result.get("observations");
        var source=new HashMap<String,Object>(Map.of("kind","run","key","R1","metric","pressure"));
        observations.add(Map.of("id","condition-R1","source",source,"text","R1의 인공 압력 조건입니다."));
        @SuppressWarnings("unchecked") var answer=(Map<String,Object>)snapshot.get("answer");
        answer.put("interpretations",List.of(Map.of("text","압력 조건도 함께 고려합니다.","observationIds",List.of("condition-R1"),"assumptions",List.of())));
        validator.answer(response(snapshot),"인공 질문");
        source.put("kind","summary");
        assertThatThrownBy(()->validator.answer(response(snapshot),"인공 질문")).hasMessageContaining("Observation metric mismatch");
    }
    @Test void savedUnitNoticeMustMatchTheSearchAndOlderSnapshotsRemainReadable()throws Exception{
        var snapshot=wire("forward");snapshot.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","mTorr")));
        validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"));
        snapshot.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","Torr")));
        assertThatThrownBy(()->validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"))).hasMessageContaining("unit assumption");
        snapshot.remove("unitAssumptions");validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"));
        var general=wire("general");general.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","mTorr")));
        assertThatThrownBy(()->validator.answer(response(general),(String)general.get("originalQuestion"))).hasMessageContaining("unit assumptions");
    }
    @SuppressWarnings("unchecked") private Map<String,Object> records(String key)throws Exception{
        return (Map<String,Object>)mapper.readValue(Files.readString(Path.of("../agent/tests/support/answer-records-wire.json")),Map.class).get(key);
    }
    @SuppressWarnings("unchecked") private AgentResponse recorded(Map<String,Object> answer){
        var inventory=((List<Map<String,Object>>)answer.get("usedRunRefs")).stream().map(r->mapper.convertValue(r,RunRef.class)).toList();
        return new AgentResponse((String)answer.get("intent"),(String)answer.get("status"),((List<Map<String,Object>>)answer.get("candidates")).stream().map(r->mapper.convertValue(r,RunRef.class)).toList(),null,(Map<String,Object>)answer.get("answerSnapshot"),inventory);
    }
    @SuppressWarnings("unchecked") private String question(Map<String,Object> answer){return (String)((Map<String,Object>)answer.get("answerSnapshot")).get("originalQuestion");}
    @SuppressWarnings("unchecked") private Map<String,Object> result(Map<String,Object> answer){return (Map<String,Object>)((Map<String,Object>)answer.get("answerSnapshot")).get("result");}
    @Test void recordReuseAnswersFromTheGraphAreAcceptedExactly()throws Exception{
        for(String key:List.of("records","notice","reverse")){var answer=records(key);validator.answer(recorded(answer),question(answer));}
    }
    @Test @SuppressWarnings("unchecked") void recordReuseRejectsMismatchedIntentRowsAndExclusions()throws Exception{
        var intent=records("records");intent.put("intent","REVERSE_SEARCH");
        assertThatThrownBy(()->validator.answer(recorded(intent),question(intent))).hasMessageContaining("Intent/tool mismatch");
        var status=records("records");result(status).put("excluded",List.of());
        assertThatThrownBy(()->validator.answer(recorded(status),question(status))).hasMessageContaining("inventory mismatch");
        var reason=records("records");var entry=(Map<String,Object>)((List<Map<String,Object>>)((List<Map<String,Object>>)result(reason).get("excluded")).getFirst().get("entries")).getFirst();entry.put("reason","GUESSED");
        assertThatThrownBy(()->validator.answer(recorded(reason),question(reason))).hasMessageContaining("Unknown record reason");
        var notice=records("notice");result(notice).put("canUndo",true);
        assertThatThrownBy(()->validator.answer(recorded(notice),question(notice))).hasMessageContaining("Notice cannot carry records");
        var threshold=records("records");result(threshold).put("threshold",1.5);
        assertThatThrownBy(()->validator.answer(recorded(threshold),question(threshold))).hasMessageContaining("Invalid record threshold");
        var hidden=records("reverse");var exclusion=(Map<String,Object>)result(hidden).get("recordExclusion");exclusion.put("canUndo",false);
        assertThatThrownBy(()->validator.answer(recorded(hidden),question(hidden))).hasMessageContaining("Invalid record exclusion");
        var forward=wire("forward");((Map<String,Object>)forward.get("result")).put("recordExclusion",Map.of());
        assertThatThrownBy(()->validator.answer(response(forward),(String)forward.get("originalQuestion"))).hasMessageContaining("Only compact searches");
    }
}
