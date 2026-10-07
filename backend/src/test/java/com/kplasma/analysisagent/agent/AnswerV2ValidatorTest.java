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
    @Test void sharedFixturePreservesZeroNullAndCompletePartial()throws Exception{
        var comparison=wire("comparison");validator.answer(response(comparison),"인공 질문");
        var general=wire("general");validator.answer(response(general),(String)general.get("originalQuestion"));
        validator.comparison(wire("partial"),response(comparison).usedRunRefs(),true);
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
    @Test void savedUnitNoticeMustMatchTheSearchAndOlderSnapshotsRemainReadable()throws Exception{
        var snapshot=wire("forward");snapshot.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","mTorr")));
        validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"));
        snapshot.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","Torr")));
        assertThatThrownBy(()->validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"))).hasMessageContaining("unit assumption");
        snapshot.remove("unitAssumptions");validator.answer(response(snapshot),(String)snapshot.get("originalQuestion"));
        var general=wire("general");general.put("unitAssumptions",List.of(Map.of("metric","pressure","unit","mTorr")));
        assertThatThrownBy(()->validator.answer(response(general),(String)general.get("originalQuestion"))).hasMessageContaining("unit assumptions");
    }
}
