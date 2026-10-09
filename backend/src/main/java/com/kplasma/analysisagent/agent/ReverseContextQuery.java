package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;

/** Validated scalar predicates. Identifiers and operators never come from unvalidated model text. */
final class ReverseContextQuery {
    private static final Map<String,String> UNITS=Map.of("pressure","mTorr","sourcePower","W","biasPower","W","meanIonEnergy","eV","ionFlux","10¹⁸ m⁻²s⁻¹","iedWidth","eV");
    private static final Set<String> OUTPUTS=Set.of("meanIonEnergy","ionFlux","iedWidth");
    private static final Map<String,String> OPERATORS=Map.of("eq","=","lt","<","lte","<=","gt",">","gte",">=");
    private final List<Map<String,Object>> constraints,goals;
    private final Set<String> required=new LinkedHashSet<>();

    ReverseContextQuery(Map<String,Object> query) {
        require(query.keySet().equals(Set.of("constraints","goals")),"reverseQuery requires constraints and goals only");
        constraints=rules(query.get("constraints"),false);goals=rules(query.get("goals"),true);
        require(!constraints.isEmpty()||!goals.isEmpty(),"reverseQuery requires at least one constraint or goal");
        constraints.forEach(rule->required.add((String)rule.get("metric")));goals.forEach(rule->required.add((String)rule.get("metric")));
    }
    Map<String,Object> normalized(){return Map.of("constraints",constraints,"goals",goals);}
    private static void require(boolean valid,String message){if(!valid)throw new IntakeException(AgentRequestService.INVALID,400,message);}
    private static List<Map<String,Object>> rules(Object raw,boolean goal){
        require(raw instanceof List<?> && ((List<?>)raw).size()<=32,"reverseQuery rules must be bounded arrays");
        List<Map<String,Object>> result=new ArrayList<>();
        for(Object value:(List<?>)raw){
            require(value instanceof Map<?,?>,"reverseQuery rule must be an object");Map<?,?> rule=(Map<?,?>)value;
            Object metric=rule.get("metric");require(metric instanceof String && UNITS.containsKey(metric) && (!goal||OUTPUTS.contains(metric)),"Unsupported reverseQuery metric");
            require(UNITS.get(metric).equals(rule.get("unit")),"reverseQuery unit must be canonical");
            String key=goal?"direction":"operator";Object operation=rule.get(key);
            require(operation instanceof String && (goal?Set.of("maximize","minimize","target_range").contains(operation):operation.equals("between")||OPERATORS.containsKey(operation)),"Unsupported reverseQuery operation");
            boolean range=operation.equals(goal?"target_range":"between");
            Set<String> fields=range?Set.of("metric",key,"min","max","unit"):goal?Set.of("metric",key,"unit"):Set.of("metric",key,"value","unit");
            require(rule.keySet().equals(fields),"Invalid reverseQuery rule fields");
            Map<String,Object> item=new LinkedHashMap<>();item.put("metric",metric);item.put(key,operation);item.put("unit",rule.get("unit"));
            for(String bound:range?List.of("min","max"):goal?List.<String>of():List.of("value")){
                Object number=rule.get(bound);require(number instanceof Number && Double.isFinite(((Number)number).doubleValue()),"reverseQuery bounds must be finite numbers");item.put(bound,((Number)number).doubleValue());
            }
            if(range)require((Double)item.get("min")<=(Double)item.get("max"),"reverseQuery bounds are reversed");
            result.add(item);
        }
        return result;
    }
    record Sql(String text,List<Object> arguments){}
    Sql select(String[] pinnedVersions){
        List<Object> args=new ArrayList<>();args.add(pinnedVersions);
        String common="usable";for(String metric:required)common+=" and "+metric+" is not null";
        for(var rule:constraints)common+=" and "+predicate(rule,args);
        // The common predicate is evaluated once. Separate condition tabs need their own matches,
        // while unusable/non-comparable rows stay available for deterministic exclusion reasons.
        String selected="common_match or not usable";
        for(String metric:required)selected+=" or "+metric+" is null";
        for(var rule:constraints)if(OUTPUTS.contains(rule.get("metric")))selected+=" or "+predicate(rule,args);
        selected+=" or not exists (select 1 from matches where common_match)";
        List<String> ordering=new ArrayList<>();
        // Existing near-match sorting is stable on catalog order for equal violations.
        // When no common match exists, preserve that order before the worker computes near matches.
        ordering.add("case when not exists (select 1 from matches where common_match) then m.run_id end asc");
        for(var goal:goals){
            String metric=(String)goal.get("metric"),direction=(String)goal.get("direction");
            if(direction.equals("target_range")){
                double min=(Double)goal.get("min"),max=(Double)goal.get("max");
                ordering.add("case when "+metric+" between ?::float8 and ?::float8 then 0 else 1 end");args.add(min);args.add(max);
                ordering.add("case when "+metric+" between ?::float8 and ?::float8 then abs("+metric+"::numeric - ?::numeric) when "+metric+" < ?::float8 then ?::numeric - "+metric+"::numeric else "+metric+"::numeric - ?::numeric end asc nulls last");
                args.add(min);args.add(max);args.add(min/2+max/2);args.add(min);args.add(min);args.add(max);
            }else ordering.add(metric+(direction.equals("maximize")?" desc":" asc")+" nulls last");
        }
        ordering.add("m.run_id asc");ordering.add("m.registration_sequence asc");
        String columns=String.join(",",required.stream().sorted().map(metric->scalar(metric)+" as "+metric).toList());
        String sql="with normalized as (select v.id,v.run_id,v.registration_sequence,v.summary,coalesce(v.summary->>'qualityStatus'='VERIFIED' and v.summary->>'convergenceStatus'='CONVERGED' and v.summary->>'catalogStatus'='READY',false) as usable,"+columns+" from run_version v where v.id=any(?::uuid[])), matches as (select normalized.*,("+common+") as common_match from normalized) select m.summary::text,jsonb_array_length(v.full_run->'sourceFiles') from matches m join run_version v on v.id=m.id where "+selected+" order by "+String.join(",",ordering);
        return new Sql(sql,args);
    }
    private static String predicate(Map<String,Object> rule,List<Object> args){
        String metric=(String)rule.get("metric"),operator=(String)rule.get("operator");
        if(operator.equals("between")){args.add(rule.get("min"));args.add(rule.get("max"));return metric+" between ?::float8 and ?::float8";}
        args.add(rule.get("value"));return metric+" "+OPERATORS.get(operator)+" ?::float8";
    }
    private static String scalar(String metric){
        String value=OUTPUTS.contains(metric)?"v.summary->'metrics'->'"+metric+"'":"v.summary->'"+metric+"'";
        String text=OUTPUTS.contains(metric)?"v.summary->'metrics'->>'"+metric+"'":"v.summary->>'"+metric+"'";
        // PostgreSQL rejects decimal underflow rather than rounding to binary64 zero. Keep
        // unusually tiny values in the NULL branch so they are returned for exact worker normalization.
        String raw="case when jsonb_typeof("+value+")='number' then case when abs(("+text+")::numeric)<=1.7976931348623157e308::numeric and (("+text+")::numeric=0 or abs(("+text+")::numeric)>=4.9406564584124654e-324::numeric) then ("+text+")::float8 end end";
        String unit="coalesce(v.summary->'units'->>'"+metric+"','"+UNITS.get(metric)+"')";
        if(metric.equals("pressure"))return "case when "+unit+"='mTorr' then "+raw+" when "+unit+"='Torr' then case when abs(("+raw+"))<=1.7976931348623157e305::float8 then ("+raw+")*1000::float8 end end";
        if(metric.equals("ionFlux"))return "case when "+unit+" in ('10¹⁸ m⁻²s⁻¹','10^18 m^-2s^-1','10^18 m^-2 s^-1') then "+raw+" when "+unit+" in ('m⁻²s⁻¹','m^-2s^-1','m^-2 s^-1','m-2s-1') then case when ("+raw+")=0 or abs(("+raw+"))>=4.9406564584124654e-306::float8 then ("+raw+")/1e18::float8 end end";
        return "case when "+unit+"='"+UNITS.get(metric)+"' then "+raw+" end";
    }
}
