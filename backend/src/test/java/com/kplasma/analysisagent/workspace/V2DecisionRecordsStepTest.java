package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;

import static org.assertj.core.api.Assertions.assertThat;

/** v2 decision_records step API. Every Run and record here is synthetic. */
@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class V2DecisionRecordsStepTest extends WorkspaceTestSupport {
    private static final String COST_NOTE = "비용이 높아 예산 초과(인공)";
    private String root;
    private JsonNode claim;

    @Test void searchGroupFeedsRecordsAndTheRemainingRunsFeedAComparison() throws Exception {
        decision("EXP-1", decisionRecordFixture());
        start("검색 후보 중 비용 반려 후보를 빼고 비교해줘");
        plan(
            tool("search", "reverse_search", List.of(), Map.of()),
            tool("records", "decision_records", List.of("search"), Map.of("action", "exclude", "runs", group("search"))),
            tool("compare", "compare_runs", List.of("records"), Map.of("runs", group("records"))));
        var searched = List.of(refs.get(2), refs.get(0), refs.get(1));
        String search = saveSearch(searched);

        String records = reserve("records", Map.of("action", "exclude", "threshold", 1,
            "runs", searched, "candidateExecutionId", search));
        var first = records(records);
        assertThat(first).hasSize(1);
        assertThat(first.get(0).get("candidates").get(1).get("note").asString()).isEqualTo(COST_NOTE);
        assertThat(first.get(0).has("authorName")).isFalse();
        decision("EXP-2", decisionRecordFixture());
        assertThat(records(records)).describedAs("the first read is pinned for the request").isEqualTo(first);
        assertThat(manifest().get("decisionRecords")).isEqualTo(first);

        var remaining = List.of(refs.get(2), refs.get(0));
        var result = recordResult(remaining, List.of(refs.get(1)));
        save(records, "records", Map.of("executionId", records, "stepId", "records", "status", "verified",
            "outputs", Map.of("toolResult", result, "candidates", remaining, "excluded", List.of(refs.get(1))),
            "runRefs", searched, "groupId", "records"));

        String compare = reserve("compare", Map.of("runs", remaining, "candidateExecutionId", records));
        assertThat(sendInternal(root + "/steps/" + compare + "/context", fence()).statusCode())
            .describedAs("a comparison may take the Runs left by a record step").isEqualTo(200);

        var event = new LinkedHashMap<String, Object>(fence());
        event.put("eventKey", "records-ready");
        event.put("type", "results.ready");
        event.put("payload", Map.of("executionIds", List.of(records)));
        long revision = internal(root + "/events", event).path("seq").longValue();
        var published = ok("GET", "/api/agent" + root + "/results?resultRevision=" + revision, null, null).path("results");
        assertThat(published.get(0).path("toolResult").path("kind").asString()).isEqualTo("decision_records");
        assertThat(published.get(0).path("toolResult").path("excluded").get(0).path("runId")).isEqualTo(refs.get(1).get("runId"));
    }

    @Test void searchSourceMustBeTheWholeSavedGroup() throws Exception {
        start("검색 후보 일부의 기록을 보여줘");
        plan(
            tool("search", "reverse_search", List.of(), Map.of()),
            tool("records", "decision_records", List.of("search"), Map.of("action", "view", "runs", group("search"))));
        String search = saveSearch(List.of(refs.get(2), refs.get(0), refs.get(1)));
        String records = reserve("records", Map.of("action", "view",
            "runs", List.of(refs.get(2), refs.get(0)), "candidateExecutionId", search));
        assertThat(sendInternal(root + "/steps/" + records + "/decision-records", fence()).statusCode()).isEqualTo(400);
        assertThat(manifest() == null || !manifest().has("decisionRecords")).isTrue();
    }

    @Test void confirmedActiveRunIsAllowedAndOtherRunsAreRejected() throws Exception {
        decision("EXP-1", decisionRecordFixture());
        var reference = new LinkedHashMap<String, Object>();
        reference.put("stateToken", token());
        reference.put("activeRun", refs.get(1));
        reference.put("candidateReference", null);
        ok("PUT", "/api/workspace/reference", reference, null);
        start("이 Run이 이전에 왜 반려됐어?");
        plan(
            tool("other", "decision_records", List.of(), Map.of("action", "view", "runs", Map.of("context_key", "activeRun"))),
            tool("view", "decision_records", List.of(), Map.of("action", "view", "runs", Map.of("context_key", "activeRun"))),
            tool("lookup", "forward_lookup", List.of(), Map.of()));

        String other = reserve("other", Map.of("action", "view", "runs", List.of(refs.get(0))));
        assertThat(sendInternal(root + "/steps/" + other + "/decision-records", fence()).statusCode())
            .describedAs("a Run outside the confirmed context").isEqualTo(400);

        String view = reserve("view", Map.of("action", "view", "runs", List.of(refs.get(1))));
        assertThat(sendInternal(root + "/steps/" + view + "/decision-records", fence(), null).statusCode()).isEqualTo(401);
        var stale = new LinkedHashMap<String, Object>(fence());
        stale.put("claimGeneration", claim.get("claimGeneration").longValue() + 1);
        assertThat(sendInternal(root + "/steps/" + view + "/decision-records", stale).statusCode()).isEqualTo(409);
        assertThat(records(view)).hasSize(1);

        String lookup = reserve("lookup", Map.of());
        assertThat(sendInternal(root + "/steps/" + lookup + "/decision-records", fence()).statusCode())
            .describedAs("only a decision_records step reads records").isEqualTo(400);
        assertThat(sendInternal(root + "/steps/" + lookup + "/context", fence()).statusCode())
            .describedAs("a record-only manifest can still be materialized by a later step").isEqualTo(200);
        var manifest = manifest();
        assertThat(manifest.get("decisionRecords")).hasSize(1);
        assertThat(manifest.get("catalogRunRefs").isArray()).isTrue();
    }

    private void start(String text) throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", text, "stateToken", token(), "graphVersion", "v2"), UUID.randomUUID().toString());
        root = "/requests/" + request.get("requestId").asString();
        claim = internal("/claim", Map.of("workerId", "v2-records", "leaseSeconds", 60, "supportedGraphVersions", List.of("v2")));
    }

    private Map<String, Object> fence() {
        var body = new LinkedHashMap<String, Object>();
        body.put("claimGeneration", claim.get("claimGeneration"));
        body.put("requestRevision", claim.get("requestRevision"));
        return body;
    }

    private static Map<String, Object> group(String step) {
        return Map.of("step_id", step, "field", "candidates", "scope", Map.of("kind", "candidate_group"));
    }

    private static Map<String, Object> tool(String id, String tool, List<String> dependsOn, Map<String, Object> inputs) {
        return Map.of("id", id, "kind", "tool", "tool", tool, "depends_on", dependsOn, "inputs", inputs);
    }

    @SafeVarargs private void plan(Map<String, Object>... steps) throws Exception {
        var draft = new LinkedHashMap<String, Object>();
        draft.put("schema_version", 1);
        draft.put("base_revision", null);
        draft.put("steps", List.of(steps));
        var body = fence();
        body.put("payload", draft);
        assertThat(internal(root + "/plans", body).get("revision").asInt()).isEqualTo(1);
    }

    private String reserve(String step, Map<String, Object> inputs) throws Exception {
        var body = fence();
        body.put("planRevision", 1);
        body.put("stepId", step);
        body.put("payload", inputs);
        return internal(root + "/steps", body).get("executionId").asString();
    }

    private void save(String execution, String step, Map<String, Object> result) throws Exception {
        var body = fence();
        body.put("payload", result);
        internal(root + "/steps/" + execution + "/result", body);
    }

    private String saveSearch(List<JsonNode> candidates) throws Exception {
        String execution = reserve("search", Map.of("constraints", List.of()));
        internal(root + "/steps/" + execution + "/context", fence());
        save(execution, "search", Map.of("executionId", execution, "stepId", "search", "status", "verified",
            "outputs", Map.of("candidates", candidates,
                "toolResult", Map.of("kind", "reverse_search", "usedRunRefs", candidates)),
            "runRefs", candidates, "groupId", "common"));
        return execution;
    }

    private JsonNode records(String execution) throws Exception {
        return internal(root + "/steps/" + execution + "/decision-records", fence()).get("records");
    }

    private JsonNode manifest() throws Exception {
        String value = jdbc.queryForObject("select manifest::text from agent_request where id=?::uuid",
            String.class, root.substring("/requests/".length()));
        return value == null ? null : mapper.readTree(value);
    }

    private Map<String, Object> recordResult(List<JsonNode> remaining, List<JsonNode> excluded) {
        var rows = new ArrayList<JsonNode>(remaining);
        rows.addAll(excluded);
        var result = new LinkedHashMap<String, Object>();
        result.put("kind", "decision_records");
        result.put("resultStatus", "EXCLUSION_APPLIED");
        result.put("action", "exclude");
        result.put("threshold", 1);
        result.put("summaryText", "비용 반려 1건 이상이 확인된 후보 1개를 제외했습니다.");
        result.put("notice", null);
        result.put("remaining", remaining.stream().map(ref -> recordRow(ref, false)).toList());
        result.put("excluded", excluded.stream().map(ref -> recordRow(ref, true)).toList());
        result.put("canUndo", true);
        result.put("recordPolicyVersion", "cost-regex-1");
        result.put("usedRunRefs", rows);
        return result;
    }

    private Map<String, Object> recordRow(JsonNode ref, boolean rejected) {
        var entries = new ArrayList<Map<String, Object>>();
        if (rejected) {
            var entry = new LinkedHashMap<String, Object>();
            entry.put("recordId", "EXP-1");
            entry.put("runId", ref.get("runId").asString());
            entry.put("recordRunVersionId", ref.get("runVersionId").asString());
            entry.put("decision", "REJECT");
            entry.put("note", COST_NOTE);
            entry.put("sharedComment", "인공 공통 코멘트");
            entry.put("reason", "COST");
            entry.put("createdAt", "2026-09-20T00:00:00Z");
            entry.put("question", "인공 질문");
            entry.put("conditions", Map.of("pressure", 8));
            entry.put("demo", false);
            entries.add(entry);
        }
        return Map.of("runId", ref.get("runId").asString(), "runVersionId", ref.get("runVersionId").asString(),
            "count", rejected ? 1 : 0, "status", rejected ? "비용 반려 1건" : "관련 기록 없음",
            "mixed", false, "entries", entries);
    }

    private void decision(String id, Map<String, Object> record) {
        var stored = new LinkedHashMap<String, Object>(record);
        stored.put("reviewId", id);
        jdbc.update("insert into decision(review_id,workspace_id,record) values (?,1,?::jsonb)", id, mapper.writeValueAsString(stored));
    }

    private Map<String, Object> decisionRecordFixture() {
        return Map.of("id", "EXP-1", "version", 2, "authorName", "인공 작성자", "decision", "ADOPT",
            "question", "인공 질문", "overallComment", "인공 공통 코멘트", "createdAt", "2026-09-20T00:00:00Z",
            "candidates", List.of(
                Map.of("runId", refs.get(0).get("runId").asString(), "runVersionId", refs.get(0).get("runVersionId").asString(),
                    "decision", "ADOPT", "note", "인공 채택", "conditions", Map.of("pressure", 6)),
                Map.of("runId", refs.get(1).get("runId").asString(), "runVersionId", refs.get(1).get("runVersionId").asString(),
                    "decision", "REJECT", "note", COST_NOTE, "conditions", Map.of("pressure", 8))));
    }

    private JsonNode internal(String path, Map<String, ?> body) throws Exception {
        var response = sendInternal(path, body);
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);
        return json(response);
    }

    private HttpResponse<String> sendInternal(String path, Map<String, ?> body) throws Exception {
        return sendInternal(path, body, "synthetic-worker-token");
    }

    private HttpResponse<String> sendInternal(String path, Map<String, ?> body, String token) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/internal/agent" + path))
            .header("Content-Type", "application/json");
        if (token != null) request.header("X-Agent-Token", token);
        return HttpClient.newHttpClient().send(request.POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),
            HttpResponse.BodyHandlers.ofString());
    }
}
