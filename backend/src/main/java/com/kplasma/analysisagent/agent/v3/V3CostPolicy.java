package com.kplasma.analysisagent.agent.v3;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.regex.Pattern;

/** V3-only cost-clause classification, mirrored by decision_rag/policy.py. */
public final class V3CostPolicy {
    public static final String VERSION="cost-regex-2";
    private static final String JS_SPACE="\t\n\u000b\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff";
    private static final String DOT="[^\\n\\r\\u2028\\u2029]";
    private static final Pattern NO_COST=compile("(비용|원가|가격)<D>{0,15}(없|않|아니|아님|무관|괜찮|적정)");
    private static final Pattern TRANSITION=compile("하지만|그러나|다만|반면|지만|으나");
    private static final Pattern CLAUSE_BOUNDARY=compile("[.!;\\n\\r\\u2028\\u2029]|하지만|그러나|다만|반면|지만|으나");
    private static final Pattern COST=compile("(비용|원가|가격)<D>{0,15}(높|비싸|초과|부담|때문|문제|과다)|예산<D>{0,8}초과");
    private static final Pattern UNCERTAIN=compile("불명|불확실|미정|미확정|추정|모르|\\?|"
        +"확인<D>{0,8}(필요|중|못|대기)|(?:답변|자료)<D>{0,8}(기다|대기)|"
        +"(?:해결|해소)<D>{0,8}(가능|수<D>{0,3}있|예정|계획)");
    private static final Pattern OTHER=compile("(성능|균일도|에너지|플럭스)<D>{0,12}(때문|미달|문제|부족)");
    private static final Pattern OTHER_TOPIC=compile("성능|균일도|에너지|플럭스|담당자|작성자");
    private static final Pattern COST_TOPIC=compile("비용|원가|가격|예산");
    private static final Pattern CURRENT=compile("현재|이번|지금|이제|최종|후속");
    private static final Pattern RESOLVED=compile("(비용|원가|가격|예산)<D>{0,15}(해결|해소)");
    private static final Pattern UNRESOLVED=compile("(비용|원가|가격|예산)<D>{0,15}(해결|해소)<D>{0,8}(않|못|안\\s*됐|안\\s*되)");
    private static final Pattern REJECTION_DENIED=compile("반려<D>{0,8}(아니|않|못)|반려하지|거절하지");
    private static final Pattern COST_CAUSE=compile("(비용|원가|가격|예산)<D>{0,30}(때문|사유|원인|반려|거절|탈락)");
    private static final Pattern INHERITED_STATE=compile(
        "^(?:(?:현재|이번|지금|이제|최종|후속)(?:검토)?(?:에서는|에는|은|는|에)?\\s*)?"
        +"(?:(?:그|이)\\s*(?:문제|사유|이유)(?:은|는|이|가)?\\s*)?"
        +"(?:해결|해소|적정|괜찮|무관|불명|불확실|미정|미확정|추정|모르|확인|높|비싸|초과|부담|과다|반려|거절)|"
        +"^그\\s*때문");

    private V3CostPolicy(){}
    private static Pattern compile(String expression){return Pattern.compile(expression.replace("<D>",DOT));}
    private static boolean matches(Pattern pattern,String text){return pattern.matcher(text).find();}
    private static String trim(String value){
        int start=0,end=value.length();
        while(start<end&&JS_SPACE.indexOf(value.charAt(start))>=0)start++;
        while(end>start&&JS_SPACE.indexOf(value.charAt(end-1))>=0)end--;
        return value.substring(start,end);
    }
    private static boolean costMatch(Pattern pattern,String text){
        var matcher=pattern.matcher(text);
        while(matcher.find())if(!matches(OTHER_TOPIC,matcher.group()))return true;
        return false;
    }
    private static String costState(String clause){
        if(matches(UNCERTAIN,clause))return "UNCLEAR";
        if(costMatch(UNRESOLVED,clause))return "COST";
        if(matches(REJECTION_DENIED,clause))return costMatch(NO_COST,clause)?"NO_COST":"UNCLEAR";
        if(costMatch(NO_COST,clause)||costMatch(RESOLVED,clause))return "NO_COST";
        if(costMatch(COST,clause))return "COST";
        return null;
    }
    private record Observation(String state,boolean current,boolean explicitCause){}

    public static String classify(String note){
        String text=trim(note==null?"":note);
        if(text.isEmpty())return "MISSING";
        var observations=new ArrayList<Observation>();
        boolean competingClause=false,competingReason=false;
        for(String part:CLAUSE_BOUNDARY.split(text)){
            String clause=trim(part);if(clause.isEmpty())continue;
            boolean hasCost=matches(COST_TOPIC,clause);
            boolean inherited=!observations.isEmpty()&&!hasCost&&!matches(OTHER_TOPIC,clause)
                &&matches(INHERITED_STATE,clause);
            if(!hasCost&&!inherited){competingClause|=matches(OTHER_TOPIC,clause);competingReason|=matches(OTHER,clause);continue;}
            String analysis=hasCost?clause:"비용 "+CURRENT.matcher(clause).replaceAll("");
            String state=costState(analysis);
            if(state!=null)observations.add(new Observation(state,matches(CURRENT,clause),costMatch(COST_CAUSE,analysis)));
        }
        if(!observations.isEmpty()){
            var states=new HashSet<String>();for(var observation:observations)states.add(observation.state());
            if(states.size()>1){
                var current=new ArrayList<String>();
                for(var observation:observations)if(observation.current())current.add(observation.state());
                if(!current.isEmpty()&&new HashSet<>(current).size()==1&&observations.getLast().current())return current.getLast();
                return "UNCLEAR";
            }
            String state=observations.getFirst().state();
            if("COST".equals(state)&&competingClause&&(matches(TRANSITION,text)||competingReason)
                &&observations.stream().noneMatch(Observation::explicitCause))return "UNCLEAR";
            return state;
        }
        return matches(OTHER,text)?"OTHER":"UNCLEAR";
    }
}
