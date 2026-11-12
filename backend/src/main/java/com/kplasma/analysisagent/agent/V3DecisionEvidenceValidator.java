package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto.AgentResponse;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.agent.v3.V3CostPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.regex.Pattern;
import tools.jackson.databind.ObjectMapper;

/** Checks local decision citations against this request's frozen, projected records. */
final class V3DecisionEvidenceValidator {
    private static final String CODE="INVALID_DECISION_EVIDENCE";
    private static final String JS_SPACE="\t\n\u000b\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff";
    private static final String DOT="[^\\n\\r\\u2028\\u2029]";
    private static final Pattern NO_COST=Pattern.compile("(비용|원가|가격)"+DOT+"{0,15}(없|않|아니|아님|무관|괜찮|적정)");
    private static final Pattern TRANSITION=Pattern.compile("해결|해소|지만|그러나|다만|반면");
    private static final Pattern COST=Pattern.compile("(비용|원가|가격)"+DOT+"{0,15}(높|비싸|초과|부담|때문|문제|과다)|예산"+DOT+"{0,8}초과");
    private static final Pattern UNCERTAIN=Pattern.compile("불명|확인|추정|모르|\\?");
    private static final Pattern OTHER=Pattern.compile("(성능|균일도|에너지|플럭스)"+DOT+"{0,12}(때문|미달|문제|부족)");
    private static final Pattern RUN_ID=Pattern.compile("RUN-[A-Z0-9-]+");
    private static final Set<String> ACTIONS=Set.of("PROPOSED_RAG_RETRIEVAL","VIEW_RECORDS","APPLY_EXISTING_COST_RULE",
        "ASK_SCOPE","ASK_THRESHOLD","INVALID_THRESHOLD","UNSUPPORTED_EXCLUSION_REASON","RECORD_REQUEST_NOT_RECOGNIZED");
    private final ObjectMapper mapper;

    V3DecisionEvidenceValidator(ObjectMapper mapper){this.mapper=mapper;}
    private void check(boolean valid,String message){if(!valid)throw new IntakeException(CODE,400,message);}
    @SuppressWarnings("unchecked") private Map<String,Object> object(Object value){
        check(value instanceof Map<?,?>,"Decision evidence requires an object");
        check(((Map<?,?>)value).keySet().stream().allMatch(String.class::isInstance),"Invalid decision object keys");
        return (Map<String,Object>)value;
    }
    private List<?> array(Object value){check(value instanceof List<?> && ((List<?>)value).size()<=10_000,"Invalid decision evidence array");return (List<?>)value;}
    private void fields(Map<String,Object> value,String... expected){check(value.keySet().equals(Set.of(expected)),"Decision evidence fields mismatch");}
    private String text(Object value,int maximum){check(value instanceof String&&!((String)value).isBlank()&&((String)value).length()<=maximum,"Invalid decision evidence text");return (String)value;}
    private String plain(Object value,int maximum){check(value instanceof String&&((String)value).length()<=maximum,"Invalid decision evidence text");return (String)value;}
    private boolean finite(Object value){return value instanceof Number number&&Double.isFinite(number.doubleValue());}
    private int integer(Object value,int maximum){check(finite(value)&&((Number)value).doubleValue()>=0&&((Number)value).doubleValue()<=maximum&&((Number)value).doubleValue()==Math.rint(((Number)value).doubleValue()),"Invalid decision evidence count");return ((Number)value).intValue();}
    private String hashText(Object value){String hash=text(value,64);check(hash.matches("[0-9a-f]{64}"),"Invalid decision source hash");return hash;}
    private RunRef ref(Object value){var map=object(value);fields(map,"runId","runVersionId");String id=text(map.get("runId"),64),version=text(map.get("runVersionId"),64);try{UUID.fromString(version);}catch(IllegalArgumentException error){throw new IntakeException(CODE,400,"Invalid decision scope version");}return new RunRef(id,version);}
    private List<RunRef> refs(Object value){var result=array(value).stream().map(this::ref).toList();check(new HashSet<>(result).size()==result.size(),"Duplicate decision scope reference");return result;}
    private List<String> strings(Object value){var result=array(value).stream().map(item->text(item,300)).toList();check(new HashSet<>(result).size()==result.size(),"Duplicate decision evidence identifier");return result;}
    private static String rawText(Object value){return value instanceof String text?text:"";}

    private Object sorted(Object value){
        if(value instanceof Map<?,?> map){var result=new TreeMap<String,Object>();for(var entry:map.entrySet()){check(entry.getKey() instanceof String,"Invalid decision record key");result.put((String)entry.getKey(),sorted(entry.getValue()));}return result;}
        if(value instanceof List<?> list)return list.stream().map(this::sorted).toList();
        check(value==null||value instanceof String||value instanceof Boolean||finite(value),"Unsupported decision source value");return value;
    }
    String canonicalHash(Object value){return sha(mapper.writeValueAsString(sorted(value)));}
    static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}

    private void collectManifestRefs(Object value,Set<RunRef> refs){
        if(!(value instanceof List<?> rows))return;
        for(Object item:rows){var row=object(item);if(row.get("runId") instanceof String&&row.get("runVersionId") instanceof String)
            refs.add(new RunRef((String)row.get("runId"),(String)row.get("runVersionId")));}
    }

    void validate(AgentResponse answer,Map<String,Object> manifest){
        check(manifest!=null&&manifest.get("decisionRecords") instanceof List<?>,"Decision records were not pinned for this request");
        var evidence=object(answer.answerSnapshot().get("decisionEvidence"));
        fields(evidence,"schemaVersion","kind","status","synthetic","answer","scopeRunRefs","citations","rules","retrieval","snapshotFingerprint","limitations");
        check(integer(evidence.get("schemaVersion"),1)==1&&"decision_rag".equals(evidence.get("kind")),"Unknown decision evidence schema");
        String status=text(evidence.get("status"),80);check(status.matches("[A-Z_]+"),"Invalid decision evidence status");
        check(evidence.get("synthetic") instanceof Boolean,"Decision evidence requires a source label");
        text(evidence.get("answer"),65_536);
        for(Object limitation:array(evidence.get("limitations")))text(limitation,2048);
        var scope=refs(evidence.get("scopeRunRefs"));check(scope.size()<=5000,"Decision scope is too large");
        Set<RunRef> allowed=new HashSet<>();
        for(String key:List.of("catalogRunRefs","selectedRunRefs","runs","referencedRuns"))collectManifestRefs(manifest.get(key),allowed);
        check(allowed.containsAll(scope)&&answer.usedRunRefs()!=null&&new HashSet<>(answer.usedRunRefs()).containsAll(scope),"Decision scope is outside materialized answer Runs");
        if("decision_rag".equals(answer.answerSnapshot().get("kind")))check(scope.equals(answer.usedRunRefs()),"Decision-only answer scope mismatch");
        var recordList=array(manifest.get("decisionRecords"));
        check(hashText(evidence.get("snapshotFingerprint")).equals(canonicalHash(recordList)),"Decision snapshot fingerprint mismatch");
        Map<String,Map<String,Object>> records=new LinkedHashMap<>();
        for(Object item:recordList){var record=object(item);String id=text(record.get("reviewId")!=null?record.get("reviewId"):record.get("id"),200);check(records.putIfAbsent(id,record)==null,"Duplicate pinned decision identifier");}
        var citations=array(evidence.get("citations"));check(citations.size()<=5,"Too many decision citations");
        var citationIds=new HashSet<String>();var documentIds=new HashSet<String>();
        Set<String> scopeIds=new LinkedHashSet<>(scope.stream().map(RunRef::runId).toList());
        for(Object item:citations)validateCitation(object(item),records,scopeIds,citationIds,documentIds);
        if(scope.isEmpty())check("ASK_SCOPE".equals(status)&&citations.isEmpty(),"Empty decision scope must request a scope");
        else check(!"ASK_SCOPE".equals(status),"A populated decision scope cannot request a scope");
        var retrieval=object(evidence.get("retrieval"));
        int totalInScope=integer(retrieval.get("totalInScope"),1_000_000);
        check(integer(retrieval.get("returned"),5)==citations.size(),"Decision citation count mismatch");
        check(totalInScope>=citations.size(),"Decision retrieval inventory is smaller than its citations");
        if(retrieval.containsKey("model"))text(retrieval.get("model"),300);
        else check("COMPLETE_RULE_AGGREGATION_WITH_PROOF".equals(retrieval.get("strategy")),"Semantic retrieval must identify its model");
        if(retrieval.containsKey("similarityIsProbability"))check(Boolean.FALSE.equals(retrieval.get("similarityIsProbability")),"Similarity is not a probability");
        validateRules(object(evidence.get("rules")),records,scopeIds);
    }

    private void validateCitation(Map<String,Object> citation,Map<String,Map<String,Object>> records,Set<String> scope,
                                  Set<String> citationIds,Set<String> documentIds){
        fields(citation,"citationId","documentId","recordId","subjectRunId","recordRunVersionId","attribution","quote","score","decision","createdAt","sourceNoteSha256","sourceRecordSha256");
        check(citationIds.add(text(citation.get("citationId"),96))&&documentIds.add(text(citation.get("documentId"),300)),"Duplicate decision citation");
        var record=records.get(text(citation.get("recordId"),200));check(record!=null,"Decision citation record was not pinned");
        check(hashText(citation.get("sourceRecordSha256")).equals(canonicalHash(record)),"Decision record source hash mismatch");
        check(citation.get("score")==null||finite(citation.get("score")),"Invalid decision similarity score");
        String role=text(citation.get("attribution"),40);String note;
        if("SHARED_UNASSIGNED".equals(role)){
            check(record.get("version") instanceof Number n&&n.intValue()==2&&array(record.get("candidates")).size()>1,"Shared citation requires a multi-candidate record");
            check(citation.get("subjectRunId")==null&&citation.get("recordRunVersionId")==null&&citation.get("decision")==null,"Shared note cannot belong to an individual Run");
            check(recordRefs(record).stream().anyMatch(scope::contains),"Shared citation is outside the scope");
            note=rawText(record.get("overallComment"));
            check(Objects.equals(citation.get("documentId"),citation.get("recordId")+":SHARED"),"Decision document identifier mismatch");
            check(citation.get("createdAt")==null||Objects.equals(citation.get("createdAt"),record.get("createdAt")),"Decision citation date mismatch");
        }else{
            check(Set.of("PER_RUN","REFERENCE_ONLY").contains(role),"Unknown decision attribution");
            String subject=text(citation.get("subjectRunId"),64);var entry=entry(record,subject);
            check(entry!=null,"Decision note is not attributable to its cited subject");
            check(Objects.equals(citation.get("documentId"),citation.get("recordId")+":"+subject),"Decision document identifier mismatch");
            if("PER_RUN".equals(role))check(scope.contains(subject),"Decision subject is outside scope");
            else check(recordRefs(record).stream().anyMatch(scope::contains),"Reference-only evidence is outside the scope");
            check(Objects.equals(citation.get("recordRunVersionId"),entry.version())&&Objects.equals(citation.get("decision"),entry.decision()),"Decision citation version or decision mismatch");
            check(Objects.equals(citation.get("createdAt"),record.get("createdAt")),"Decision citation date mismatch");
            note=entry.note();
        }
        String quote=plain(citation.get("quote"),4000);
        int end=note.offsetByCodePoints(0,Math.min(2000,note.codePointCount(0,note.length())));
        check(quote.equals(note.substring(0,end)),"Decision quote is not the original note prefix");
        check(hashText(citation.get("sourceNoteSha256")).equals(sha(note)),"Decision note source hash mismatch");
    }

    private record Entry(String version,String decision,String note){}
    private Entry entry(Map<String,Object> record,String runId){
        if(record.get("version") instanceof Number n&&n.intValue()==2){
            var candidates=array(record.get("candidates"));
            for(Object item:candidates){var candidate=object(item);if(runId.equals(candidate.get("runId"))){
                String note=rawText(candidate.get("note"));if(note.isEmpty()&&candidates.size()==1)note=rawText(record.get("overallComment"));
                return new Entry(rawText(candidate.get("runVersionId")),rawText(candidate.get("decision")),note);
            }}
            return null;
        }
        if(!runId.equals(record.get("targetRunId")))return null;
        var ref=object(record.get("targetRunRef"));
        return new Entry(rawText(ref.get("runVersionId")),rawText(record.get("decision")),rawText(record.get("comment")));
    }
    private Set<String> recordRefs(Map<String,Object> record){
        var refs=new HashSet<String>();if(record.get("targetRunId") instanceof String id)refs.add(id);
        if(record.get("comparedRunIds") instanceof List<?> ids)for(Object id:ids)if(id instanceof String text)refs.add(text);
        if(record.get("candidates") instanceof List<?> rows)for(Object value:rows){var row=object(value);if(row.get("runId") instanceof String id)refs.add(id);}
        return refs;
    }
    private static String trimJs(String value){int start=0,end=value.length();while(start<end&&JS_SPACE.indexOf(value.charAt(start))>=0)start++;while(end>start&&JS_SPACE.indexOf(value.charAt(end-1))>=0)end--;return value.substring(start,end);}
    private static String reason(String note,String runId){
        var foreign=RUN_ID.matcher(note);while(foreign.find())if(!foreign.group().equals(runId))return "UNCLEAR";
        String text=trimJs(note);if(text.isEmpty())return "MISSING";
        if(NO_COST.matcher(text).find())return "NO_COST";
        if(TRANSITION.matcher(text).find())return "UNCLEAR";
        if(COST.matcher(text).find()&&!UNCERTAIN.matcher(text).find())return "COST";
        return OTHER.matcher(text).find()?"OTHER":"UNCLEAR";
    }
    private static String reason(String note,String runId,String policy){
        // Previously saved policy1 results keep their original interpretation.
        if(!V3CostPolicy.VERSION.equals(policy))return reason(note,runId);
        var foreign=RUN_ID.matcher(note);while(foreign.find())if(!foreign.group().equals(runId))return "UNCLEAR";
        return V3CostPolicy.classify(note);
    }
    private void validateRules(Map<String,Object> rules,Map<String,Map<String,Object>> records,Set<String> scope){
        if("disabled".equals(rules.get("policy"))) {
            fields(rules,"policy","action","threshold","perRun","excludedRunIds","remainingRunIds","completeAggregation");
            check("DISABLED".equals(rules.get("action"))&&rules.get("threshold")==null
                &&array(rules.get("perRun")).isEmpty()&&array(rules.get("excludedRunIds")).isEmpty()
                &&Boolean.FALSE.equals(rules.get("completeAggregation"))
                &&new HashSet<>(strings(rules.get("remainingRunIds"))).equals(scope),"Disabled rules must not claim an aggregation or exclusion");
            return;
        }
        var required=new HashMap<>(rules);required.remove("aggregationScope");
        fields(required,"policy","action","threshold","perRun","excludedRunIds","remainingRunIds","completeAggregation");
        if(rules.containsKey("aggregationScope"))check("ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY".equals(rules.get("aggregationScope")),"Unknown decision aggregation scope");
        String policy=text(rules.get("policy"),80);
        check(Set.of("cost-regex-1",V3CostPolicy.VERSION).contains(policy)&&Boolean.TRUE.equals(rules.get("completeAggregation")),"Unknown or incomplete decision policy");
        String action=text(rules.get("action"),80);check(ACTIONS.contains(action),"Unknown decision policy action");
        check(scope.isEmpty()=="ASK_SCOPE".equals(action),"Decision policy scope action mismatch");
        check(rules.get("threshold")==null||finite(rules.get("threshold")),"Invalid decision policy threshold");
        boolean exclude="APPLY_EXISTING_COST_RULE".equals(action);
        check(!exclude||(finite(rules.get("threshold"))&&((Number)rules.get("threshold")).doubleValue()>=1
            &&((Number)rules.get("threshold")).doubleValue()==Math.rint(((Number)rules.get("threshold")).doubleValue())),"Exclusion threshold must be a positive integer");
        Set<String> seen=new LinkedHashSet<>(),expectedExcluded=new LinkedHashSet<>();
        for(Object value:array(rules.get("perRun"))){
            var row=object(value);fields(row,"runId","count","status","mixed","costRejectionRecordIds");
            String run=text(row.get("runId"),64);check(scope.contains(run)&&seen.add(run),"Decision rule scope mismatch");
            Set<String> costIds=new HashSet<>(),reasons=new HashSet<>(),decisions=new HashSet<>();boolean any=false,missingRejected=false;
            for(var source:records.entrySet()){
                Entry entry=entry(source.getValue(),run);if(entry==null)continue;any=true;
                String reason=reason(entry.note(),run,policy);reasons.add(reason);decisions.add(entry.decision());
                if("REJECT".equals(entry.decision())&&"COST".equals(reason))costIds.add(source.getKey());
                if("REJECT".equals(entry.decision())&&"MISSING".equals(reason))missingRejected=true;
            }
            check(integer(row.get("count"),records.size())==costIds.size()&&new HashSet<>(strings(row.get("costRejectionRecordIds"))).equals(costIds),"Decision counts do not match complete pinned records");
            check(row.get("mixed") instanceof Boolean&&Objects.equals(row.get("mixed"),decisions.contains("ADOPT")&&decisions.contains("REJECT")),"Decision conflict flag mismatch");
            String status=!any?"관련 기록 없음":!costIds.isEmpty()?"비용 반려 "+costIds.size()+"건":reasons.contains("NO_COST")?"비용 문제 없음 기록":missingRejected?"반려 사유 미기록":reasons.contains("UNCLEAR")?"사유 확인 필요":"비용 반려 근거 없음";
            check(status.equals(row.get("status")),"Decision rule status mismatch");
            if(exclude&&costIds.size()>=((Number)rules.get("threshold")).doubleValue())expectedExcluded.add(run);
        }
        check(seen.equals(scope),"Decision aggregation must cover the entire scope");
        Set<String> remaining=new HashSet<>(scope);remaining.removeAll(expectedExcluded);
        check(new HashSet<>(strings(rules.get("excludedRunIds"))).equals(expectedExcluded)
            &&new HashSet<>(strings(rules.get("remainingRunIds"))).equals(remaining),"Decision exclusion does not match the fixed policy");
    }
}
