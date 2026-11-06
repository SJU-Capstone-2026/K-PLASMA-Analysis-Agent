package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;

import static org.assertj.core.api.Assertions.assertThat;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class AgentGraphVersionTest extends WorkspaceTestSupport {
    @Test void planReviewsAreDurableAndLimitedToThreePerRequest() throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", "조건에 맞는 Run 조회", "stateToken", token(), "graphVersion", "v2"), "plan-review-limit");
        var claim = claim(Map.of("workerId", "review-worker", "leaseSeconds", 60,
            "supportedGraphVersions", List.of("v2")));
        String path = "/requests/" + request.get("requestId").asString() + "/model-attempts";
        var body = new LinkedHashMap<String,Object>(Map.of("claimGeneration", claim.get("claimGeneration"),
            "requestRevision", claim.get("requestRevision"), "kind", "PLAN_REVIEW", "key", "review:1"));
        var first = internal(path, body);
        assertThat(first.get("callAllowed").asBoolean()).isTrue();
        var outcome = Map.of("data", Map.of("status", "PASS", "plan_digest", "synthetic-digest"));
        internal(path + "/" + first.get("attemptId").asString() + "/complete",
            Map.of("claimGeneration", claim.get("claimGeneration"), "requestRevision", claim.get("requestRevision"),
                "payload", outcome));
        var replay = internal(path, body);
        assertThat(replay.get("callAllowed").asBoolean()).isFalse();
        assertThat(replay.path("outcome").path("data").path("plan_digest").asString()).isEqualTo("synthetic-digest");
        for(int i=2;i<=3;i++){body.put("key", "review:"+i);assertThat(internal(path,body).get("callAllowed").asBoolean()).isTrue();}
        body.put("key", "review:4");
        assertThat(sendInternal(path,body).statusCode()).isEqualTo(409);
    }

    @Test void planReviewsConsumeTheExistingGlobalModelBudget() throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", "Run 조회", "stateToken", token(), "graphVersion", "v2"), "plan-review-total");
        var claim = claim(Map.of("workerId", "review-worker", "leaseSeconds", 60,
            "supportedGraphVersions", List.of("v2")));
        String path = "/requests/" + request.get("requestId").asString() + "/model-attempts";
        var kinds = List.of("PLAN_REVIEW", "PLAN_REVIEW", "PLAN_REVIEW", "PLAN_INITIAL", "REPLAN", "REPLAN",
            "COMPOSE", "COMPOSE", "COMPOSE", "ANSWER_REWRITE", "PARTIAL_COMPOSE", "REVIEW", "REVIEW");
        for(int i=0;i<kinds.size();i++)assertThat(internal(path,
            Map.of("claimGeneration", claim.get("claimGeneration"), "requestRevision", claim.get("requestRevision"),
                "kind", kinds.get(i), "key", "budget:"+i)).get("callAllowed").asBoolean()).isTrue();
        assertThat(sendInternal(path, Map.of("claimGeneration",claim.get("claimGeneration"),
            "requestRevision",claim.get("requestRevision"),"kind","REVIEW","key","over-budget")).statusCode()).isEqualTo(409);
    }

    @Test void catalogTagRequiresSavedSelectionAndKeepsItsVersion() throws Exception {
        var ref = refs.getFirst();
        var origin = new LinkedHashMap<String, Object>();
        origin.put("ref", ref);
        origin.put("kind", "catalog_tag");
        origin.put("turnId", null);
        origin.put("groupId", null);
        var submission = new LinkedHashMap<String, Object>(Map.of(
            "text", "태그한 Run의 압력을 알려줘", "stateToken", token(), "graphVersion", "v2",
            "attachedRunRefs", List.of(ref), "referenceOrigins", List.of(origin)));
        assertThat(send("POST", "/api/agent/requests", submission, "unselected-tag").statusCode()).isEqualTo(400);

        var saved = ok("PUT", "/api/workspace/reference", Map.of("stateToken", token(), "activeRun", ref,
            "candidateReference", Map.of("kind", "단일 Run", "runs", List.of(ref), "catalogRefs", List.of(ref))), null);
        assertThat(saved.path("candidateReference").path("catalogRefs").get(0)).isEqualTo(ref);
        jdbc.update("update run set current_version_id=null where run_id=?", ref.path("runId").asString());
        submission.put("stateToken", saved.get("stateToken"));
        var request = ok("POST", "/api/agent/requests", submission, "selected-tag");
        var context = jdbc.queryForObject("select context_snapshot::text from agent_request where id=?::uuid",
            String.class, request.get("requestId").asString());
        var entry = mapper.readTree(context).path("comparisonReference").path("entries").get(0);
        assertThat(entry.path("ref")).isEqualTo(ref);
        assertThat(entry.path("origin").path("kind").asString()).isEqualTo("catalog_tag");
    }

    @Test void pinsFirstRequestAndDoesNotAssignItToOldWorker() throws Exception {
        var body = Map.of("text", "IED란?", "stateToken", token(), "graphVersion", "v2");
        var request = ok("POST", "/api/agent/requests", body, "graph-v2");
        assertThat(request.get("graphVersion").asString()).isEqualTo("v2");
        assertThat(state().get("conversation").get("agentGraphVersion").asString()).isEqualTo("v2");
        assertThat(ok("POST", "/api/agent/requests", body, "graph-v2").get("requestId"))
            .isEqualTo(request.get("requestId"));
        assertThat(claim(Map.of("workerId", "old-worker", "leaseSeconds", 60)).get("request").isNull()).isTrue();
        var v2 = claim(Map.of("workerId", "v2-worker", "leaseSeconds", 60, "supportedGraphVersions", List.of("v2")));
        assertThat(v2.get("request").get("requestId")).isEqualTo(request.get("requestId"));
    }

    @Test void modelReservationIsDurableAndCannotAuthorizeADuplicateCall() throws Exception {
        var body = Map.of("text", "IED란?", "stateToken", token(), "graphVersion", "v2");
        var request = ok("POST", "/api/agent/requests", body, "model-reservation");
        var claim = claim(Map.of("workerId", "v2-worker", "leaseSeconds", 60, "supportedGraphVersions", List.of("v2")));
        var permitRequest = Map.of("claimGeneration", claim.get("claimGeneration"),
            "requestRevision", claim.get("requestRevision"), "kind", "PLAN_INITIAL", "key", "initial");
        String path = "/requests/" + request.get("requestId").asString() + "/model-attempts";
        var first = internal(path, permitRequest);
        assertThat(first.get("callAllowed").asBoolean()).isTrue();
        var repeated = internal(path, permitRequest);
        assertThat(repeated.get("attemptId")).isEqualTo(first.get("attemptId"));
        assertThat(repeated.get("callAllowed").asBoolean()).isFalse();

        jdbc.update("update agent_request set lease_until=clock_timestamp()-interval '1 second' where id=?::uuid",
            request.get("requestId").asString());
        var recovered = claim(Map.of("workerId", "replacement", "leaseSeconds", 60,
            "supportedGraphVersions", List.of("v2")));
        var restored = internal(path, Map.of("claimGeneration", recovered.get("claimGeneration"),
            "requestRevision", recovered.get("requestRevision"), "kind", "PLAN_INITIAL", "key", "initial"));
        assertThat(restored.get("attemptId")).isEqualTo(first.get("attemptId"));
        assertThat(restored.get("callAllowed").asBoolean()).isFalse();
        assertThat(sendInternal(path+"/"+first.get("attemptId").asString()+"/complete",
            Map.of("claimGeneration",claim.get("claimGeneration"),"requestRevision",claim.get("requestRevision"),
                   "payload",Map.of("data","late response"))).statusCode()).isEqualTo(409);
    }

    @Test void savedStepsAreImmutableAndCannotBeReexecuted() throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", "값을 비교해줘", "stateToken", token(), "graphVersion", "v2"), "step-reservation");
        var claim = claim(Map.of("workerId", "v2-worker", "leaseSeconds", 60, "supportedGraphVersions", List.of("v2")));
        var body = new LinkedHashMap<String,Object>();
        body.put("claimGeneration", claim.get("claimGeneration"));
        body.put("requestRevision", claim.get("requestRevision"));
        String root = "/requests/" + request.get("requestId").asString();
        var draft = new LinkedHashMap<String,Object>();
        draft.put("schema_version",1);
        draft.put("base_revision",null);
        draft.put("request_mode","data_request");
        draft.put("requirements",List.of());
        draft.put("steps",List.of(Map.of("id","calc","kind","derive","operation","max")));
        body.put("payload",draft);
        assertThat(internal(root+"/plans",body).get("revision").asInt()).isEqualTo(1);
        body.put("planRevision",1);
        body.put("stepId","calc");
        var inputs = Map.of("values",List.of(1,1.0e17));
        body.put("payload",inputs);
        var execution = internal(root+"/steps",body);
        assertThat(execution.get("callAllowed").asBoolean()).isTrue();
        String id = execution.get("executionId").asString();
        String path = root + "/steps/" + id + "/result";
        var result = Map.of("executionId",id,"stepId","calc","status","verified",
            "outputs",Map.of("value",1.0e17),"runRefs",List.of());
        body.put("payload",result);
        assertThat(internal(path,body).get("result").get("outputs").get("value").asDouble()).isEqualTo(1.0e17);
        body.put("payload",inputs);
        var restored = internal(root+"/steps",body);
        assertThat(restored.get("callAllowed").asBoolean()).isFalse();
        assertThat(restored.get("result").get("executionId").asString()).isEqualTo(id);
        body.put("payload",Map.of("executionId",id,"stepId","calc","status","verified",
            "outputs",Map.of("value",99),"runRefs",List.of()));
        assertThat(sendInternal(path,body).statusCode()).isEqualTo(409);
        var snapshot = Map.ofEntries(Map.entry("implementationId","v2"),Map.entry("graphVersion","v2"),
            Map.entry("schemaVersion",1),Map.entry("intent","COMPOSITE_ANSWER"),Map.entry("question","값을 비교해줘"),
            Map.entry("answer","검증된 계산입니다."),Map.entry("confirmedContext",Map.of()),Map.entry("stepResults",List.of(result)),
            Map.entry("evidence",List.of()),Map.entry("executionStatus","COMPLETE"),
            Map.entry("review",Map.of("status","UNAVAILABLE","answers",List.of())),Map.entry("budget",Map.of()));
        var commit=Map.of("claimGeneration",claim.get("claimGeneration"),
            "requestRevision",claim.get("requestRevision"),"answer",Map.of("intent","COMPOSITE_ANSWER",
            "status","COMPLETE","usedRunRefs",List.of(),"answerSnapshot",snapshot));
        var finalized=internal(root+"/finalize",commit);
        assertThat(finalized.get("status").asString()).isEqualTo("COMPLETED");
        assertThat(internal(root+"/finalize",commit).get("turnId")).isEqualTo(finalized.get("turnId"));
    }

    @Test void candidateSelectionKeepsPinnedVersionAndExecutionOrigin() throws Exception {
        var request = ok("POST","/api/agent/requests",
            Map.of("text","후보 중 두 Run을 비교해줘","stateToken",token(),"graphVersion","v2"),"candidate-source");
        var claim = claim(Map.of("workerId","v2-worker","leaseSeconds",60,"supportedGraphVersions",List.of("v2")));
        var body = new LinkedHashMap<String,Object>();
        body.put("claimGeneration",claim.get("claimGeneration"));
        body.put("requestRevision",claim.get("requestRevision"));
        String id = request.get("requestId").asString();
        String root = "/requests/"+id;
        var draft = new LinkedHashMap<String,Object>();
        draft.put("schema_version",1);
        draft.put("base_revision",null);
        draft.put("steps",List.of(Map.of("id","search","kind","tool","tool","reverse_search")));
        body.put("payload",draft);
        internal(root+"/plans",body);
        body.put("planRevision",1);
        body.put("stepId","search");
        body.put("payload",Map.of("constraints",List.of()));
        String execution = internal(root+"/steps",body).get("executionId").asString();
        internal(root+"/steps/"+execution+"/context",body);
        var candidates=List.of(refs.get(2),refs.get(0),refs.get(1));
        String fluxUnit="10¹⁸ m⁻²s⁻¹";
        var snapshots=new LinkedHashMap<String,Object>();
        for (int i=0;i<candidates.size();i++) {
            var ref=candidates.get(i);
            snapshots.put(ref.get("runVersionId").asString(),Map.of(
                "runId",ref.get("runId"),"runVersionId",ref.get("runVersionId"),
                "metrics",Map.of("ionFlux",75.25+i,"meanIonEnergy",155+i,"iedWidth",6),
                "units",Map.of("ionFlux",fluxUnit,"meanIonEnergy","eV","iedWidth","eV")));
        }
        body.put("payload",Map.of("executionId",execution,"stepId","search","status","verified",
            "outputs",Map.of("candidates",candidates,"toolResult",Map.of(
                "kind","reverse_search","usedRunRefs",candidates,"runsByVersion",snapshots,
                "constraints",List.of(Map.of("metric","ionFlux","operator","gte","value",50,"unit",fluxUnit)),
                "goals",List.of(Map.of("metric","meanIonEnergy","direction","maximize","unit","eV")))),
            "runRefs",candidates,"groupId","common"));
        internal(root+"/steps/"+execution+"/result",body);
        jdbc.update("update run set current_version_id=null where run_id=?",refs.get(0).get("runId").asString());
        internal(root+"/needs-input",Map.of("claimGeneration",claim.get("claimGeneration"),
            "requestRevision",claim.get("requestRevision"),"pendingInput",Map.of("type","run_selection",
                "id","v2-picker","message","검색한 후보 중 두 Run을 선택해 주세요.","sourceExecutionId",execution,"minSelections",2,"maxSelections",2)));
        var picker=ok("GET","/api/agent"+root+"/run-options?pendingInputId=v2-picker",null,null);
        for(String suffix:List.of("/run-options?format=2&pendingInputId=v2-picker",
                "/run-options/count?pendingInputId=v2-picker","/run-selection?pendingInputId=v2-picker")) {
            assertThat(send("GET","/api/agent"+root+suffix,null,null).statusCode()).isEqualTo(409);
        }
        assertThat(send("POST","/api/agent"+root+"/run-selection",Map.of(
            "pendingInputId","v2-picker","expectedRequestRevision",0,"expectedSelectionRevision",0,
            "operation","all"),"wrong-picker-format").statusCode()).isEqualTo(409);
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection",Integer.class)).isZero();
        assertThat(ok("GET","/api/agent"+root+"/run-options?pendingInputId=v2-picker",null,null)).isEqualTo(picker);
        var criteria=picker.path("searchCriteria");
        assertThat(criteria.path("constraints").get(0).path("operator").asString()).isEqualTo("gte");
        assertThat(criteria.path("constraints").get(0).path("value").asInt()).isEqualTo(50);
        assertThat(criteria.path("goals").get(0).path("metric").asString()).isEqualTo("meanIonEnergy");
        var options=picker.get("options");
        assertThat(options.size()).isEqualTo(3);
        assertThat(options.get(1).get("ref")).isEqualTo(candidates.get(1));
        assertThat(options.get(2).get("ref")).isEqualTo(candidates.get(2));
        assertThat(options.get(0).get("ref")).isEqualTo(candidates.getFirst());
        var measurements=options.get(0).path("searchMeasurements");
        assertThat(measurements.path("ionFlux").path("value").asDouble()).isEqualTo(75.25);
        assertThat(measurements.path("ionFlux").path("unit").asString()).isEqualTo(fluxUnit);
        assertThat(measurements.path("meanIonEnergy").path("value").asInt()).isEqualTo(155);
        assertThat(measurements.has("iedWidth")).isFalse();
        assertThat(options.get(1).path("searchMeasurements").path("ionFlux").path("value").asDouble()).isEqualTo(76.25);
        for (var wrongKeys:List.of(List.of(options.get(0).get("key")),
                List.of(options.get(0).get("key"),options.get(1).get("key"),options.get(2).get("key")))) {
            assertThat(send("POST","/api/agent"+root+"/resume",Map.of(
                "expectedRequestRevision",claim.get("requestRevision"),"pendingInputId","v2-picker",
                "input",Map.of("type","run_selection","runKeys",wrongKeys)),
                "wrong-count-"+wrongKeys.size()).statusCode()).isEqualTo(400);
        }
        var resumed=ok("POST","/api/agent"+root+"/resume",Map.of("expectedRequestRevision",claim.get("requestRevision"),
            "pendingInputId","v2-picker","input",Map.of("type","run_selection","runKeys",
                List.of(options.get(0).get("key"),options.get(1).get("key")))),"v2-candidate-input");
        var origin=resumed.get("inputEvents").get(0).get("input").get("comparisonReference").get("entries").get(0).get("origin");
        assertThat(origin.get("executionId").asString()).isEqualTo(execution);
        assertThat(origin.get("stepId").asString()).isEqualTo("search");
        assertThat(origin.get("groupId").asString()).isEqualTo("common");
    }

    @Test void referenceChangesFenceAnActiveV2StepWithoutLegacyOperationKind() throws Exception {
        var request = ok("POST","/api/agent/requests",
            Map.of("text","선택한 실험을 비교해줘","stateToken",token(),"graphVersion","v2"),"reference-fence");
        var claim = claim(Map.of("workerId","v2-worker","leaseSeconds",60,"supportedGraphVersions",List.of("v2")));
        String root="/requests/"+request.get("requestId").asString();
        var heartbeat=Map.of("claimGeneration",claim.get("claimGeneration"),"requestRevision",claim.get("requestRevision"),
            "dependsOnContext",true,"stage","execute_step");
        internal(root+"/heartbeat",heartbeat);
        var context = new LinkedHashMap<String,Object>();
        context.put("stateToken",token());
        context.put("activeRun",refs.getFirst());
        context.put("candidateReference",null);
        ok("PUT","/api/workspace/reference",context,null);
        assertThat(ok("GET","/api/agent"+root,null,null).get("status").asString()).isEqualTo("CANCELLED");
        assertThat(sendInternal(root+"/heartbeat",heartbeat).statusCode()).isEqualTo(409);
    }

    private JsonNode claim(Map<String, Object> body) throws Exception {
        return internal("/claim", body);
    }

    private JsonNode internal(String path, Map<String, ?> body) throws Exception {
        var response = sendInternal(path,body);
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);
        return json(response);
    }

    private HttpResponse<String> sendInternal(String path, Map<String, ?> body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/internal/agent" + path))
            .header("Content-Type", "application/json").header("X-Agent-Token", "synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        return HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
    }
}
