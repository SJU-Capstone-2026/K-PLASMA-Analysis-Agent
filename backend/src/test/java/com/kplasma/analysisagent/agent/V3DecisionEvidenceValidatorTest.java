package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto.AgentResponse;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.SnapshotValidator;
import com.kplasma.analysisagent.agent.v3.V3CostPolicy;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;

/** Entirely artificial record metadata; no database, embedding model, or real Run payload. */
class V3DecisionEvidenceValidatorTest {
    private static final RunRef A=new RunRef("RUN-TEST-A","00000000-0000-4000-8000-000000000001");
    private static final RunRef OLD_A=new RunRef("RUN-TEST-A","00000000-0000-4000-8000-000000000002");
    private static final RunRef B=new RunRef("RUN-TEST-B","00000000-0000-4000-8000-000000000003");
    private static final String CREATED="2026-01-01T00:00:00Z";
    private final ObjectMapper mapper=new ObjectMapper();
    private final V3DecisionEvidenceValidator validator=new V3DecisionEvidenceValidator(mapper);

    private static Map<String,Object> m(Object... entries){
        var map=new LinkedHashMap<String,Object>();
        for(int i=0;i<entries.length;i+=2)map.put((String)entries[i],entries[i+1]);
        return map;
    }
    private static Map<String,Object> ref(RunRef ref){return m("runId",ref.runId(),"runVersionId",ref.runVersionId());}
    private static Map<String,Object> rev(String id,RunRef ref,String decision,String note){
        return m("reviewId",id,"version",1,"targetRunId",ref.runId(),"targetRunRef",ref(ref),
            "decision",decision,"comment",note,"createdAt",CREATED,"isDemo",true);
    }
    private Map<String,Object> citation(Map<String,Object> record,RunRef subject,String note,String role){
        String id=(String)record.get("reviewId");
        return m("citationId","S1","documentId",id+":"+(subject==null?"SHARED":subject.runId()),
            "recordId",id,"subjectRunId",subject==null?null:subject.runId(),
            "recordRunVersionId",subject==null?null:subject.runVersionId(),"attribution",role,
            "quote",note.substring(0,note.offsetByCodePoints(0,Math.min(2000,note.codePointCount(0,note.length())))),
            "score",0.85,"decision",subject==null?null:record.get("decision"),"createdAt",subject==null?null:CREATED,
            "sourceNoteSha256",V3DecisionEvidenceValidator.sha(note),"sourceRecordSha256",validator.canonicalHash(record));
    }
    private Map<String,Object> rules(String run,int count,String status,boolean mixed,List<String> ids){
        return m("policy","cost-regex-1","action","PROPOSED_RAG_RETRIEVAL","threshold",null,
            "aggregationScope","ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY",
            "perRun",List.of(m("runId",run,"count",count,"status",status,"mixed",mixed,"costRejectionRecordIds",ids)),
            "excludedRunIds",List.of(),"remainingRunIds",List.of(run),"completeAggregation",true);
    }
    private Map<String,Object> evidence(List<Map<String,Object>> records,List<RunRef> scope,List<Map<String,Object>> citations,Map<String,Object> rules){
        return m("schemaVersion",1,"kind","decision_rag","status",scope.isEmpty()?"ASK_SCOPE":"ANSWERED","synthetic",true,
            "answer","인공 판단 기록 검토 결과입니다.","scopeRunRefs",scope.stream().map(V3DecisionEvidenceValidatorTest::ref).toList(),
            "citations",citations,"rules",rules,"retrieval",m("totalInScope",citations.size(),"returned",citations.size(),
            "model","artificial-test-model","similarityIsProbability",false),"snapshotFingerprint",validator.canonicalHash(records),
            "limitations",List.of("테스트용 인공 기록입니다."));
    }
    private Map<String,Object> snapshot(Map<String,Object> evidence,List<RunRef> scope){
        var refs=scope.stream().map(V3DecisionEvidenceValidatorTest::ref).toList();
        String status="ASK_SCOPE".equals(evidence.get("status"))?"ASK_SCOPE":"EVIDENCE_READY";
        return m("implementationId","v1","graphVersion","v1","schemaVersion",2,"kind","decision_rag",
            "summary","저장된 판단 기록을 확인했습니다.","originalQuestion","인공 판단 기록 질문",
            "toolSelection",m("call_id","code-rag-test","name","decision_rag","arguments",m()),"resolvedInputs",m(),
            "result",m("kind","decision_rag","resultStatus",status,"usedRunRefs",refs),"answer",null,
            "contextProvenance",m(),"inputHistory",List.of(),"usedRunRefs",refs,"versions",m(),"decisionEvidence",evidence);
    }
    private AgentResponse response(Map<String,Object> snapshot){
        @SuppressWarnings("unchecked") var refs=(List<Map<String,Object>>)snapshot.get("usedRunRefs");
        var inventory=refs.stream().map(r->mapper.convertValue(r,RunRef.class)).toList();
        String kind=(String)snapshot.get("kind");
        String intent=Map.of("decision_rag","DECISION_RAG","compare_runs","RUN_COMPARISON","forward_lookup","FORWARD_LOOKUP",
            "reverse_search","REVERSE_SEARCH","generate_answer","GENERAL_ANSWER").get(kind);
        return new AgentResponse(intent,(String)((Map<?,?>)snapshot.get("result")).get("resultStatus"),List.of(),null,snapshot,inventory);
    }
    private record Fixture(Map<String,Object> snapshot,Map<String,Object> manifest,Map<String,Object> evidence,Map<String,Object> citation){}
    private Fixture fixture(){
        var rejected=rev("REV-TEST-1",OLD_A,"REJECT","비용이 높아 반려했습니다.");
        var adopted=rev("REV-TEST-2",A,"ADOPT","비용 문제 없음");
        var records=List.of(rejected,adopted);
        var citation=citation(rejected,OLD_A,(String)rejected.get("comment"),"PER_RUN");
        var evidence=evidence(records,List.of(A),List.of(citation),rules(A.runId(),1,"비용 반려 1건",true,List.of("REV-TEST-1")));
        return new Fixture(snapshot(evidence,List.of(A)),m("catalogRunRefs",List.of(ref(A),ref(B)),"decisionRecords",records),evidence,citation);
    }
    private void valid(Fixture fixture){validator.validate(response(fixture.snapshot()),fixture.manifest());}
    private void invalid(Fixture fixture){assertThatThrownBy(()->valid(fixture)).isInstanceOf(IntakeException.class);}

    @Test void distinctVersionsOfTheSameRunAreAllowedButAnExactScopePairCannotRepeat(){
        var original=fixture();
        var scope=List.of(A,OLD_A);
        original.evidence().put("scopeRunRefs",scope.stream().map(V3DecisionEvidenceValidatorTest::ref).toList());
        original.manifest().put("catalogRunRefs",List.of(ref(A),ref(OLD_A)));
        var versioned=new Fixture(snapshot(original.evidence(),scope),original.manifest(),original.evidence(),original.citation());
        valid(versioned); // One Run's full-history count stays one; two immutable version references remain distinct.
        var duplicateScope=List.of(A,A);
        original.evidence().put("scopeRunRefs",duplicateScope.stream().map(V3DecisionEvidenceValidatorTest::ref).toList());
        invalid(new Fixture(snapshot(original.evidence(),duplicateScope),original.manifest(),original.evidence(),original.citation()));
    }

    @Test void disabledRulesCannotClaimCountsOrExclusions(){
        var f=fixture();
        var disabled=m("policy","disabled","action","DISABLED","threshold",null,"perRun",List.of(),
            "excludedRunIds",List.of(),"remainingRunIds",List.of(A.runId()),"completeAggregation",false);
        f.evidence().put("rules",disabled);valid(f);
        disabled.put("excludedRunIds",List.of(A.runId()));invalid(f);
        disabled.put("excludedRunIds",List.of());disabled.put("completeAggregation",true);invalid(f);
    }

    @Test void citationMustMatchPinnedRecordRawNoteVersionAndDocumentIdentity(){
        for(var mutation:List.of(m("recordId","REV-NOT-PINNED"),m("quote","변조한 인공 메모"),m("sourceNoteSha256","0".repeat(64)),
            m("sourceRecordSha256","0".repeat(64)),m("recordRunVersionId",A.runVersionId()),m("decision","ADOPT"),
            m("createdAt","2026-01-02T00:00:00Z"),m("documentId","another-document"))){
            var f=fixture();f.citation().putAll(mutation);invalid(f);
        }
        var f=fixture();f.evidence().put("snapshotFingerprint","0".repeat(64));invalid(f);
        f=fixture();f.evidence().put("scopeRunRefs",List.of(ref(B)));invalid(f);
        f=fixture();f.manifest().remove("decisionRecords");invalid(f);
        f=fixture();var reversed=new ArrayList<>((List<?>)f.manifest().get("decisionRecords"));
        Collections.reverse(reversed);f.manifest().put("decisionRecords",reversed);invalid(f);
    }

    @Test void fullHistoryAggregationCannotBeReplacedWithRetrievedTopKOrFakeExclusion(){
        var first=rev("REV-COUNT-1",OLD_A,"REJECT","비용이 높음");
        var second=rev("REV-COUNT-2",A,"REJECT","예산 초과");
        var records=List.of(first,second);
        var rules=rules(A.runId(),2,"비용 반려 2건",false,List.of("REV-COUNT-1","REV-COUNT-2"));
        rules.putAll(m("action","APPLY_EXISTING_COST_RULE","threshold",2,"excludedRunIds",List.of(A.runId()),"remainingRunIds",List.of()));
        var e=evidence(records,List.of(A),List.of(citation(first,OLD_A,(String)first.get("comment"),"PER_RUN")),rules);
        var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",records),e,m());
        valid(f); // Only one retrieval hit, but both saved historical decisions are counted.
        rules.put("threshold",3);invalid(f);
        rules.put("threshold",2);
        @SuppressWarnings("unchecked") var row=(Map<String,Object>)((List<?>)rules.get("perRun")).getFirst();
        row.put("count",1);invalid(f);
        row.put("count",2);row.put("mixed",true);invalid(f);
    }

    @Test void sharedCommentCannotBecomeCandidateCostRejectionEvidence(){
        var record=m("reviewId","EXP-TEST-SHARED","version",2,"overallComment","공동 검토 메모: 비용 부담",
            "createdAt",CREATED,"candidates",List.of(m("runId",A.runId(),"runVersionId",A.runVersionId(),"decision","ADOPT","note",""),
            m("runId",B.runId(),"runVersionId",B.runVersionId(),"decision","REJECT","note","비용 부담")));
        var c=citation(record,null,(String)record.get("overallComment"),"SHARED_UNASSIGNED");
        var e=evidence(List.of(record),List.of(A),List.of(c),rules(A.runId(),0,"비용 반려 근거 없음",false,List.of()));
        var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(record)),e,c);
        valid(f);
        c.put("subjectRunId",A.runId());invalid(f);
        c.put("subjectRunId",null);
        @SuppressWarnings("unchecked") var row=(Map<String,Object>)((List<?>)((Map<?,?>)e.get("rules")).get("perRun")).getFirst();
        row.put("count",1);invalid(f);
    }

    @Test void comparisonReferenceIsShownAsReferenceOnlyWithoutBorrowingItsReason(){
        var record=rev("REV-REFERENCE",B,"REJECT","비용이 높음");record.put("comparedRunIds",List.of(A.runId()));
        record.put("comparedRunRefs",List.of(ref(A)));
        var c=citation(record,B,(String)record.get("comment"),"REFERENCE_ONLY");
        var e=evidence(List.of(record),List.of(A),List.of(c),rules(A.runId(),0,"관련 기록 없음",false,List.of()));
        var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(record)),e,c);
        valid(f);c.put("attribution","PER_RUN");invalid(f);
    }

    @Test void scopedOwnerCanConservativelyKeepForeignProseAsReferenceOnly(){
        String note=B.runId()+"의 비용이 높아 반려했습니다.";
        var legacy=rev("REV-FOREIGN-PROSE-V1",OLD_A,"REJECT",note);
        var multi=m("reviewId","REV-FOREIGN-PROSE-V2","version",2,"createdAt",CREATED,"overallComment","",
            "candidates",List.of(m("runId",OLD_A.runId(),"runVersionId",OLD_A.runVersionId(),"decision","REJECT","note",note),
                m("runId",B.runId(),"runVersionId",B.runVersionId(),"decision","ADOPT","note","후보 B 메모")));
        for(var record:List.of(legacy,multi)){
            var c=citation(record,OLD_A,note,"REFERENCE_ONLY");
            c.put("decision","REJECT");
            var e=evidence(List.of(record),List.of(A),List.of(c),rules(A.runId(),0,"사유 확인 필요",false,List.of()));
            var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(record)),e,c);
            String frozenRecord=mapper.writeValueAsString(record);
            valid(f);
            assertThat(c.get("subjectRunId")).isEqualTo(A.runId());
            assertThat(c.get("recordRunVersionId")).isEqualTo(OLD_A.runVersionId());
            assertThat(c.get("quote")).isEqualTo(note);
            assertThat(c.get("sourceNoteSha256")).isEqualTo(V3DecisionEvidenceValidator.sha(note));
            assertThat(c.get("sourceRecordSha256")).isEqualTo(validator.canonicalHash(record));
            // Historical PER_RUN snapshots retain their source-owner contract; the fixed policy still counts zero.
            c.put("attribution","PER_RUN");valid(f);
            assertThat(mapper.writeValueAsString(record)).isEqualTo(frozenRecord);
        }
    }

    @Test void referenceOnlyStillRequiresRelatedPinnedSourceAndExactProvenance(){
        var unrelated=rev("REV-UNRELATED",B,"REJECT","비용이 높음");
        var unrelatedCitation=citation(unrelated,B,(String)unrelated.get("comment"),"REFERENCE_ONLY");
        var unrelatedEvidence=evidence(List.of(unrelated),List.of(A),List.of(unrelatedCitation),rules(A.runId(),0,"관련 기록 없음",false,List.of()));
        invalid(new Fixture(snapshot(unrelatedEvidence,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(unrelated)),unrelatedEvidence,unrelatedCitation));
        for(var mutation:List.of(m("sourceRecordSha256","0".repeat(64)),m("sourceNoteSha256","0".repeat(64)),
            m("quote","변조한 인공 메모"),m("subjectRunId",B.runId(),"documentId","REV-SCOPED-REFERENCE:"+B.runId(),"recordRunVersionId",B.runVersionId()),
            m("recordRunVersionId",A.runVersionId()),m("decision","ADOPT"),m("attribution","SHARED_UNASSIGNED"))){
            String note=B.runId()+"의 비용이 높음";
            var record=rev("REV-SCOPED-REFERENCE",OLD_A,"REJECT",note);
            var c=citation(record,OLD_A,note,"REFERENCE_ONLY");
            var e=evidence(List.of(record),List.of(A),List.of(c),rules(A.runId(),0,"사유 확인 필요",false,List.of()));
            var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(record)),e,c);
            valid(f);c.putAll(mutation);invalid(f);
        }
    }

    @Test void emptyScopeOnlyProducesAskScopeAndCannotBroadenToAllRecords(){
        var rules=m("policy","cost-regex-1","action","ASK_SCOPE","threshold",null,"perRun",List.of(),
            "excludedRunIds",List.of(),"remainingRunIds",List.of(),"completeAggregation",true);
        var e=evidence(List.of(),List.of(),List.of(),rules);
        var f=new Fixture(snapshot(e,List.of()),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of()),e,m());
        valid(f);
        e.put("status","ANSWERED");invalid(f);
    }

    @Test void utf8CanonicalHashAndQuoteLimitMatchPythonUnicodeCodepoints(){
        assertThat(validator.canonicalHash(m("z",List.of(1,true),"a","한글\n\"/")))
            .isEqualTo(V3DecisionEvidenceValidator.sha("{\"a\":\"한글\\n\\\"/\",\"z\":[1,true]}"));
        String note="🧪".repeat(2100);
        var record=rev("REV-UNICODE",A,"ADOPT",note);var c=citation(record,A,note,"PER_RUN");
        var e=evidence(List.of(record),List.of(A),List.of(c),rules(A.runId(),0,"사유 확인 필요",false,List.of()));
        valid(new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",List.of(record)),e,c));
        assertThat(((String)c.get("quote")).codePointCount(0,((String)c.get("quote")).length())).isEqualTo(2000);
    }

    @Test void v3CostClauseCasesShareThePythonArtificialContract() throws Exception {
        try(var input=getClass().getResourceAsStream("/v3-cost-policy-cases.json")){
            assertThat(input).isNotNull();
            var contract=mapper.readValue(input,Map.class);
            assertThat(contract.get("synthetic")).isEqualTo(true);
            for(Object value:(List<?>)contract.get("cases")){
                var row=(Map<?,?>)value;
                assertThat(V3CostPolicy.classify((String)row.get("note")))
                    .as((String)row.get("id")).isEqualTo(row.get("expected"));
            }
        }
    }

    @Test void changedCostClauseSemanticsAreVersionedAndCannotForgeOldCounts(){
        var record=rev("ART-COST-CONTRAST",A,"REJECT","비용 초과를 두 번 적었지만 하나의 심사에서 반려했다.");
        var records=List.of(record);
        var rules=rules(A.runId(),0,"사유 확인 필요",false,List.of());
        var e=evidence(records,List.of(A),List.of(),rules);
        var f=new Fixture(snapshot(e,List.of(A)),m("catalogRunRefs",List.of(ref(A)),"decisionRecords",records),e,m());
        valid(f); // Historical policy1's stored count is still valid.
        rules.put("policy",V3CostPolicy.VERSION);
        invalid(f); // The same old count cannot be relabelled as policy2.
        rules.put("perRun",List.of(m("runId",A.runId(),"count",1,"status","비용 반려 1건",
            "mixed",false,"costRejectionRecordIds",List.of("ART-COST-CONTRAST"))));
        valid(f);
        rules.put("policy","cost-regex-1");invalid(f);
    }

}
