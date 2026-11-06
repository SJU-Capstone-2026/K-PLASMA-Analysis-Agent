package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.SnapshotValidator;
import java.util.*;
import org.springframework.stereotype.Component;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** The public result contains tool cards, never execution inputs, model state or original graph arrays. */
@Component
public class AgentPublicResultProjection {
    private static final TypeReference<Map<String,Object>> MAP=new TypeReference<>() {};
    private static final String CODE="INVALID_PUBLIC_RESULT";
    private final ObjectMapper mapper;
    private final SnapshotValidator validator;
    public AgentPublicResultProjection(ObjectMapper mapper,SnapshotValidator validator) {this.mapper=mapper;this.validator=validator;}

    public List<Map<String,Object>> project(List<JsonNode> saved) {
        return saved.stream().map(result->{
            Map<String,Object> raw=mapper.convertValue(result.path("outputs").path("toolResult"),MAP);
            Map<String,Object> tool=tool(raw);
            Set<RunRef> inventory=new HashSet<>();collectRefs(tool,inventory);
            validator.compactValidated(tool,CODE,inventory);
            return Map.<String,Object>of("stepId",result.path("stepId").asString(),"executionId",result.path("executionId").asString(),
                "runRefs",mapper.convertValue(result.path("runRefs"),new TypeReference<List<RunRef>>() {}),"toolResult",tool);
        }).toList();
    }
    private void check(boolean condition) {if(!condition)throw new IntakeException(CODE,409,"Saved tool result does not match its public contract");}
    @SuppressWarnings("unchecked") private Map<String,Object> object(Object value) {check(value instanceof Map<?,?>);return (Map<String,Object>)value;}
    private List<?> array(Object value) {check(value instanceof List<?>);return (List<?>)value;}
    private Map<String,Object> pick(Map<String,Object> value,String fields) {
        Map<String,Object> result=new LinkedHashMap<>();for(String field:fields.split(" "))if(value.containsKey(field))result.put(field,value.get(field));return result;
    }
    private Map<String,Object> flatPick(Map<String,Object> value,String fields) {
        var result=pick(value,fields);for(Object datum:result.values())check(datum==null || datum instanceof String
            || datum instanceof Boolean || datum instanceof Number n && Double.isFinite(n.doubleValue()));return result;
    }
    private Map<String,Object> scalarRun(Object value) {
        var raw=object(value);
        var result=pick(raw,"runId runVersionId pressure sourcePower biasPower metrics units metricAvailability convergenceStatus qualityStatus catalogStatus registeredAt presentationScore note sourceFileCount");
        for(String field:List.of("metrics","units","metricAvailability"))if(result.containsKey(field))
            result.put(field,flatPick(object(result.get(field)),"pressure sourcePower biasPower meanIonEnergy ionFlux iedWidth"));
        if(raw.get("analysis") instanceof Map<?,?>)result.put("analysis",flatPick(object(raw.get("analysis")),"hasDistribution strictConvergence finalResidualMax electronTemperature ionTemperature gasTemperature absorbedPower alpha plasmaResistance plasmaReactance dcOffset peakToPeak currentDensityPeak electronDensity ionDensity metastableDensity neutralDensity ionFluxRaw metastableFluxRaw neutralFluxRaw"));
        for(var entry:result.entrySet())if(!Set.of("metrics","units","metricAvailability","analysis").contains(entry.getKey()))
            check(entry.getValue()==null || entry.getValue() instanceof String || entry.getValue() instanceof Number || entry.getValue() instanceof Boolean);
        for(String field:List.of("metrics","units","metricAvailability","analysis"))if(result.containsKey(field))
            for(Object datum:object(result.get(field)).values())check(datum==null || datum instanceof String || datum instanceof Number || datum instanceof Boolean);
        return result;
    }
    private Map<String,Object> rule(Object value) {return flatPick(object(value),"id metric operator comparisonOperator value min max unit tolerance direction");}
    private Map<String,Object> ref(Object value) {var raw=object(value);check(raw.get("runId") instanceof String && raw.get("runVersionId") instanceof String);return pick(raw,"runId runVersionId");}
    private List<Map<String,Object>> refs(Object value) {return array(value).stream().map(this::ref).toList();}
    private Map<String,Object> tool(Map<String,Object> raw) {
        String kind=String.valueOf(raw.get("kind"));
        if("compare_runs".equals(kind)) {
            var refs=array(raw.get("usedRunRefs")).stream().map(r->mapper.convertValue(r,RunRef.class)).toList();
            new AnswerV2Validator(validator,raw.containsKey("featurePolicyVersion")).comparison(raw,refs,false);
            return raw;
        }
        check(Set.of("forward_lookup","reverse_search").contains(kind));
        check("v1".equals(raw.get("numericPolicyVersion")) && Objects.equals(raw.get("status"),raw.get("resultStatus")));
        String fields="kind resultStatus status usedRunRefs excludedRuns defaultedUnits numericPolicyVersion ";
        fields+="forward_lookup".equals(kind)?"run selectedRun candidates deltas requestedConditions units":"processMode constraints goals objectives totalCount searchResultVersion runsByVersion commonRunRefs commonRunIds commonRecommendation objectiveResults goalResults candidateEvaluations";
        var result=pick(raw,fields);
        check(result.keySet().equals(new HashSet<>(List.of(fields.trim().split(" +")))));
        result.put("usedRunRefs",refs(raw.get("usedRunRefs")));
        result.put("excludedRuns",array(raw.get("excludedRuns")).stream().map(value->{
            var row=object(value);var excluded=new LinkedHashMap<>(ref(row));
            excluded.put("reasons",array(row.get("reasons")).stream().map(reason->flatPick(object(reason),"metric code")).toList());return excluded;
        }).toList());
        var defaulted=array(raw.get("defaultedUnits"));
        for(Object metric:defaulted)check(metric instanceof String && Set.of("pressure","sourcePower","biasPower","meanIonEnergy","ionFlux","iedWidth").contains(metric));
        result.put("defaultedUnits",List.copyOf(defaulted));
        if("forward_lookup".equals(kind)) {
            check(Set.of("EXACT","NEAREST_ONLY","NO_DATA").contains(String.valueOf(raw.get("resultStatus"))));
            for(String key:List.of("run","selectedRun"))result.put(key,raw.get(key)==null?null:scalarRun(raw.get(key)));
            result.put("candidates",array(raw.get("candidates")).stream().map(this::scalarRun).toList());
            for(String key:List.of("deltas","requestedConditions"))if(raw.get(key)!=null)result.put(key,flatPick(object(raw.get(key)),"pressure sourcePower biasPower"));
            result.put("units",flatPick(object(raw.get("units")),"pressure sourcePower biasPower meanIonEnergy ionFlux iedWidth"));
            var inventory=refs(raw.get("usedRunRefs"));var candidates=array(result.get("candidates"));
            if(raw.get("run")==null)check(inventory.isEmpty() && candidates.isEmpty() && raw.get("selectedRun")==null && "NO_DATA".equals(raw.get("resultStatus")));
            else check(inventory.size()==1 && inventory.getFirst().equals(ref(raw.get("run")))
                && inventory.getFirst().equals(ref(raw.get("selectedRun"))) && candidates.size()==1
                && inventory.getFirst().equals(ref(candidates.getFirst())) && !"NO_DATA".equals(raw.get("resultStatus")));
        } else {
            for(String key:List.of("constraints","goals","objectives"))result.put(key,array(raw.get(key)).stream().map(this::rule).toList());
            Map<String,Object> runs=new LinkedHashMap<>();object(raw.get("runsByVersion")).forEach((key,value)->{
                var run=scalarRun(value);check(key.equals(run.get("runVersionId")));runs.put(key,run);
            });result.put("runsByVersion",runs);
            result.put("commonRunRefs",refs(raw.get("commonRunRefs")));
            result.put("commonRecommendation",raw.get("commonRecommendation")==null?null:ref(raw.get("commonRecommendation")));
            result.put("objectiveResults",array(raw.get("objectiveResults")).stream().map(value->{var row=object(value);return Map.of("objective",rule(row.get("objective")),"candidateRefs",refs(row.get("candidateRefs")),"allConstraintsGuaranteed",Boolean.TRUE.equals(row.get("allConstraintsGuaranteed")));}).toList());
            check(array(raw.get("goalResults")).isEmpty());result.put("goalResults",List.of());
            result.put("candidateEvaluations",array(raw.get("candidateEvaluations")).stream().map(value->{
                var row=object(value);var evaluation=new LinkedHashMap<>(ref(row));evaluation.putAll(flatPick(row,"matchPercent"));
                evaluation.put("evaluations",array(row.get("evaluations")).stream().map(item->flatPick(object(item),"objectiveId metric operator comparisonOperator unit actual satisfied targetLabel boundaryDelta percentDelta rangeStatus baselineDelta baselinePercentDelta unavailableReason referenceValue matchPercent")).toList());return evaluation;
            }).toList());
            new AnswerV2Validator(validator).compactSearch(result);
        }
        return result;
    }
    private void collectRefs(Object value,Set<RunRef> found) {
        if(value instanceof Map<?,?> map) {if(map.get("runVersionId") instanceof String version && map.get("runId") instanceof String run)found.add(new RunRef(run,version));for(Object child:map.values())collectRefs(child,found);}
        else if(value instanceof List<?> list)for(Object child:list)collectRefs(child,found);
    }
}
