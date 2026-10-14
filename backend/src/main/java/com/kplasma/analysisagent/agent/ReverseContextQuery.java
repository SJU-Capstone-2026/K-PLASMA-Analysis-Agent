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
    private static final Map<String,String> COLUMNS=Map.of("pressure","pressure_mtorr","sourcePower","source_power_w","biasPower","bias_power_w","meanIonEnergy","mean_ion_energy_ev","ionFlux","ion_flux_1e18","iedWidth","ied_width_ev");
    Sql select(){
        List<Object> args=new ArrayList<>();
        String common="r.searchable and r.current_version_id is not null";
        for(String metric:required)common+=" and "+column(metric)+" is not null";
        for(var rule:constraints)common+=" and "+predicate(rule,args);
        List<String> branches=new ArrayList<>();
        branches.add("select r.current_version_id as id from run r where "+common);
        // Each condition tab requires only its own metric, not the other goals/constraints.
        for(var rule:constraints)if(OUTPUTS.contains(rule.get("metric")))
            branches.add("select r.current_version_id as id from run r where r.searchable and r.current_version_id is not null and "+column((String)rule.get("metric"))+" is not null and "+predicate(rule,args));
        List<String> ordering=new ArrayList<>();
        for(var goal:goals){
            String metric=column((String)goal.get("metric")),direction=(String)goal.get("direction");
            if(direction.equals("target_range")){
                double min=(Double)goal.get("min"),max=(Double)goal.get("max");
                ordering.add("case when "+metric+" between ?::float8 and ?::float8 then 0 else 1 end");args.add(min);args.add(max);
                ordering.add("case when "+metric+" between ?::float8 and ?::float8 then abs("+metric+"::numeric - ?::numeric) when "+metric+" < ?::float8 then ?::numeric - "+metric+"::numeric else "+metric+"::numeric - ?::numeric end asc nulls last");
                args.add(min);args.add(max);args.add(min/2+max/2);args.add(min);args.add(min);args.add(max);
            }else ordering.add(metric+(direction.equals("maximize")?" desc":" asc")+" nulls last");
        }
        ordering.add("r.run_id asc");ordering.add("v.registration_sequence asc");
        String sql="with selected as ("+String.join(" union ",branches)+") select v.summary::text,v.source_file_count from selected s join run_version v on v.id=s.id join run r on r.current_version_id=s.id and r.run_id=v.run_id order by "+String.join(",",ordering);
        return new Sql(sql,args);
    }
    private static String column(String metric){return "r."+COLUMNS.get(metric);}
    private static String predicate(Map<String,Object> rule,List<Object> args){
        String metric=column((String)rule.get("metric")),operator=(String)rule.get("operator");
        if(operator.equals("between")){args.add(rule.get("min"));args.add(rule.get("max"));return metric+" between ?::float8 and ?::float8";}
        args.add(rule.get("value"));return metric+" "+OPERATORS.get(operator)+" ?::float8";
    }
}
