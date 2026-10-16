package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;

/** Canonical conditions supplied by the worker; never an LLM-generated SQL or Run ID. */
final class ForwardContextQuery {
    private static final Map<String,String> UNITS=Map.of("pressure","mTorr","sourcePower","W","biasPower","W");
    private final Map<String,Double> values=new LinkedHashMap<>();

    ForwardContextQuery(Map<String,Object> query) {
        require(query.keySet().equals(UNITS.keySet()));
        for(String key:List.of("pressure","sourcePower","biasPower")) {
            Object value=query.get(key);
            require(value instanceof Number && Double.isFinite(((Number)value).doubleValue()));
            values.put(key,((Number)value).doubleValue()==0?0d:((Number)value).doubleValue());
        }
    }
    private static void require(boolean valid) {
        if(!valid)throw new IntakeException(AgentRequestService.INVALID,400,"forwardQuery requires three finite canonical condition values");
    }
    Map<String,Double> normalized(){return values;}
    String runId() {
        // Registration currently uses integer condition keys. Never truncate a query.
        if(values.values().stream().anyMatch(v->v<0||v>Integer.MAX_VALUE||v!=Math.rint(v)))return null;
        return String.format(Locale.ROOT,"RUN-P%02d-S%03d-B%04d",values.get("pressure").intValue(),values.get("sourcePower").intValue(),values.get("biasPower").intValue());
    }
    boolean matches(Map<String,Object> run) {
        if(!"READY".equals(run.get("catalogStatus"))||!"VERIFIED".equals(run.get("qualityStatus"))||!"CONVERGED".equals(run.get("convergenceStatus")))return false;
        Map<?,?> units=run.get("units") instanceof Map<?,?> map?map:Map.of();
        return values.entrySet().stream().allMatch(e->run.get(e.getKey()) instanceof Number n
            && Double.isFinite(n.doubleValue()) && n.doubleValue()==e.getValue()
            && (units.get(e.getKey())==null||UNITS.get(e.getKey()).equals(units.get(e.getKey()))));
    }
}
