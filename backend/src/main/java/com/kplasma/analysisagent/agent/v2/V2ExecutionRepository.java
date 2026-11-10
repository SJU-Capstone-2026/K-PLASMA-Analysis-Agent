package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.ingestion.IntakeException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.HashMap;
import java.util.HashSet;

/** All writes run under the parent request's fenced transaction. */
@Repository
public class V2ExecutionRepository {
    private static final Map<String, Integer> MODEL_LIMITS = Map.of(
        "PLAN_INITIAL", 1, "REPLAN", 2, "COMPOSE", 3, "ANSWER_REWRITE", 1, "PARTIAL_COMPOSE", 1, "REVIEW", 5);
    private static final Set<String> TOOLS = Set.of("forward_lookup", "reverse_search", "compare_runs", "decision_records");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public V2ExecutionRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    private void check(boolean condition, String message) {
        if (!condition) throw new IntakeException("INVALID_V2_EXECUTION", 409, message);
    }

    private String json(Object value) {
        String result = mapper.writeValueAsString(value);
        check(result.length() <= 2_000_000, "v2 record is too large");
        return result;
    }

    private JsonNode read(String value) {
        return value == null ? null : mapper.readTree(value);
    }

    private int count(String sql, Object... args) {
        return jdbc.queryForObject(sql, Integer.class, args);
    }

    public Map<String, Object> acceptPlan(UUID request, long inputRevision, JsonNode draft) {
        check(draft != null && draft.isObject() && draft.path("schema_version").asInt() == 1
            && draft.path("steps").isArray() && draft.path("steps").size() <= 16
            && !draft.path("base_revision").isMissingNode(), "invalid plan");
        var previous = jdbc.query(
            "select revision, plan::text, input_revision, plan=?::jsonb from agent_v2_plan_revision where request_id=? order by revision desc limit 1",
            (rs, n) -> new Plan(rs.getInt(1), read(rs.getString(2)), rs.getLong(3), rs.getBoolean(4)), json(draft), request
        ).stream().findFirst().orElse(null);
        int base = draft.path("base_revision").asInt(0);
        if (previous != null && previous.inputRevision() == inputRevision && previous.samePlan())
            return Map.of("revision", previous.revision(), "plan", previous.plan());
        check(base == (previous == null ? 0 : previous.revision()) && base < 3, "stale or exhausted plan revision");
        int revision = base + 1;
        jdbc.update("insert into agent_v2_plan_revision values (?,?,?,?::jsonb)",
            request, revision, inputRevision, json(draft));
        return Map.of("revision", revision, "plan", draft);
    }

    public Map<String, Object> reserveStep(
        UUID request, long generation, long inputRevision, int revision, String stepId, JsonNode inputs
    ) {
        check(stepId != null && !stepId.isBlank() && inputs != null && inputs.isObject(), "invalid step reservation");
        var draft = jdbc.query(
            "select plan::text from agent_v2_plan_revision where request_id=? and revision=?",
            (rs, n) -> read(rs.getString(1)), request, revision
        ).stream().findFirst().orElse(null);
        check(draft != null && revision == count("select max(revision) from agent_v2_plan_revision where request_id=?", request),
            "step must belong to current plan");
        JsonNode step = null;
        for (var candidate : draft.path("steps")) {
            if (stepId.equals(candidate.path("id").asString())) {
                step = candidate;
                break;
            }
        }
        check(step != null, "unregistered step");
        boolean tool = "tool".equals(step.path("kind").asString());
        check(tool ? TOOLS.contains(step.path("tool").asString()) : "derive".equals(step.path("kind").asString()),
            "step is not executable");
        var previous = jdbc.query(
            "select id, inputs=?::jsonb, result::text from agent_step_execution where request_id=? and plan_revision=? and input_revision=? and step_id=?",
            (rs, n) -> new Step(rs.getObject(1, UUID.class), rs.getBoolean(2), read(rs.getString(3))),
            json(inputs), request, revision, inputRevision, stepId
        ).stream().findFirst().orElse(null);
        if (previous != null) {
            check(previous.sameInputs(), "step input changed");
            return reservation("executionId", previous.id(), false, "result", previous.result());
        }
        if (tool) {
            int calls = count("""
                select count(*) from agent_step_execution e
                join agent_v2_plan_revision p on p.request_id=e.request_id and p.revision=e.plan_revision
                where e.request_id=? and exists (
                    select 1 from jsonb_array_elements(p.plan->'steps') s
                    where s->>'id'=e.step_id and s->>'kind'='tool')
                """, request);
            check(calls < 12, "tool budget exhausted");
        }
        UUID id = UUID.randomUUID();
        jdbc.update("""
            insert into agent_step_execution(id,request_id,plan_revision,step_id,claim_generation,input_revision,inputs)
            values (?,?,?,?,?,?,?::jsonb)
            """, id, request, revision, stepId, generation, inputRevision, json(inputs));
        return reservation("executionId", id, true, "result", null);
    }

    public JsonNode activeStepInputs(UUID request, long generation, long inputRevision, UUID id) {
        var values = jdbc.query("""
            select inputs::text from agent_step_execution
            where request_id=? and claim_generation=? and input_revision=? and id=? and result is null
            """, (rs, n) -> read(rs.getString(1)), request, generation, inputRevision, id);
        check(values.size() == 1, "active step reservation required");
        return values.getFirst();
    }

    /**
     * A comparison or decision-record step may take a whole candidate group from a verified
     * search, or the remaining Runs of an earlier decision-record step.
     */
    public boolean matchesSearchCandidates(UUID request, UUID target, String sourceExecutionId, JsonNode refs) {
        return count("""
            select count(*) from agent_step_execution target
            join agent_v2_plan_revision p on p.request_id=target.request_id and p.revision=target.plan_revision
            join agent_step_execution source on source.request_id=target.request_id
            cross join lateral jsonb_array_elements(p.plan->'steps') step
            where target.request_id=? and target.id=? and source.id::text=?
              and source.plan_revision<=target.plan_revision and source.input_revision<=target.input_revision
              and step->>'id'=target.step_id and step->>'tool' in ('compare_runs','decision_records')
              and step#>>'{inputs,runs,step_id}'=source.step_id
              and step#>>'{inputs,runs,field}'='candidates'
              and step#>>'{inputs,runs,scope,kind}'='candidate_group'
              and source.result->>'status'='verified'
              and source.result#>>'{outputs,toolResult,kind}' in ('reverse_search','decision_records')
              and source.result#>'{outputs,candidates}'=?::jsonb
            """, request, target, sourceExecutionId, json(refs)) == 1;
    }

    /** The reserved execution belongs to a plan step that calls {@code tool}. */
    public boolean isToolStep(UUID request, UUID execution, String tool) {
        return count("""
            select count(*) from agent_step_execution e
            join agent_v2_plan_revision p on p.request_id=e.request_id and p.revision=e.plan_revision
            cross join lateral jsonb_array_elements(p.plan->'steps') step
            where e.request_id=? and e.id=? and step->>'id'=e.step_id
              and step->>'kind'='tool' and step->>'tool'=?
            """, request, execution, tool) == 1;
    }

    public void pinStepSources(UUID request, UUID id, Object refs) {
        int updated = jdbc.update("""
            update agent_step_execution set source_refs=?::jsonb where request_id=? and id=?
              and result is null and (source_refs is null or source_refs=?::jsonb)
            """, json(refs), request, id, json(refs));
        check(updated == 1, "step sources cannot change");
    }

    public Map<String, Object> saveStep(UUID request, long generation, long inputRevision, UUID id, JsonNode result) {
        check(result != null && result.isObject() && id.toString().equals(result.path("executionId").asString())
            && result.path("runRefs").isArray() && result.path("outputs").isObject()
            && Set.of("verified", "empty", "partial", "failed", "blocked", "skipped").contains(result.path("status").asString()),
            "invalid step result");
        var sources = jdbc.query(
            "select source_refs::text from agent_step_execution where request_id=? and id=?",
            (rs, n) -> read(rs.getString(1)), request, id
        );
        check(sources.size() == 1, "unknown step execution");
        JsonNode source = sources.getFirst();
        var refs = result.path("runRefs");
        for (var ref : refs) {
            check(source != null && contains(source, ref), "step Run is outside its frozen source");
        }
        var output = result.path("outputs");
        var tool = output.path("toolResult");
        if (!tool.isMissingNode()) {
            check(tool.isObject() && tool.path("usedRunRefs").equals(refs), "result Run inventory changed");
        }
        for (var ref : output.path("candidates")) {
            check(contains(refs, ref), "candidate is outside the execution inventory");
        }
        int updated = jdbc.update("""
            update agent_step_execution set result=?::jsonb
            where id=? and request_id=? and claim_generation=? and input_revision=? and step_id=?
              and (result is null or result=?::jsonb)
            """, json(result), id, request, generation, inputRevision, result.path("stepId").asString(), json(result));
        check(updated == 1, "step result cannot be overwritten or attached to another claim");
        return Map.of("result", result);
    }

    public Map<String, Object> reserveModel(UUID request, long generation, long inputRevision, String kind, String key) {
        check(kind != null && MODEL_LIMITS.containsKey(kind) && key != null && !key.isBlank() && key.length() <= 200,
            "invalid model reservation");
        var previous = jdbc.query(
            "select id,kind,outcome::text,deadline::text,input_revision from agent_v2_model_attempt where request_id=? and attempt_key=?",
            (rs, n) -> new Attempt(rs.getObject(1, UUID.class), rs.getString(2), read(rs.getString(3)), rs.getString(4), rs.getLong(5)),
            request, key
        ).stream().findFirst().orElse(null);
        if (previous != null) {
            check(previous.kind().equals(kind) && previous.inputRevision() == inputRevision, "model attempt key changed role or input");
            var result = reservation("attemptId", previous.id(), false, "outcome", previous.outcome());
            result.put("deadline", previous.deadline());
            return result;
        }
        check(count("select count(*) from agent_v2_model_attempt where request_id=?", request) < 13
            && count("select count(*) from agent_v2_model_attempt where request_id=? and kind=?", request, kind)
               < MODEL_LIMITS.get(kind), "model budget exhausted");
        UUID id = UUID.randomUUID();
        String deadline = jdbc.queryForObject("""
            insert into agent_v2_model_attempt(id,request_id,attempt_key,kind,claim_generation,input_revision,deadline)
            values (?,?,?,?,?,?,clock_timestamp()+interval '30 seconds') returning deadline::text
            """, String.class, id, request, key, kind, generation, inputRevision);
        var result = reservation("attemptId", id, true, "outcome", null);
        result.put("deadline", deadline);
        return result;
    }

    public Map<String, Object> completeModel(UUID request, long generation, long inputRevision, UUID id, JsonNode outcome) {
        check(outcome != null && outcome.isObject(), "invalid model outcome");
        int updated = jdbc.update("""
            update agent_v2_model_attempt set outcome=?::jsonb
            where id=? and request_id=? and claim_generation=? and input_revision=?
              and (outcome is null or outcome=?::jsonb)
            """, json(outcome), id, request, generation, inputRevision, json(outcome));
        check(updated == 1, "model outcome cannot be overwritten or attached to another claim");
        return Map.of("outcome", outcome);
    }

    public boolean matchesSavedResult(UUID request, JsonNode result) {
        return Boolean.TRUE.equals(jdbc.queryForObject("""
            select exists(select 1 from agent_step_execution where request_id=? and result=?::jsonb)
            """, Boolean.class, request, json(result)));
    }

    public List<JsonNode> savedResults(UUID request) {
        return new ArrayList<>(jdbc.query("""
            select result::text from agent_step_execution
            where request_id=? and result is not null order by plan_revision, step_id
            """, (rs, n) -> read(rs.getString(1)), request));
    }

    /** An old binding remains readable; new bindings must follow the current graph, not the history table. */
    public List<JsonNode> publicResults(UUID request,List<String> executionIds,boolean currentOnly) {
        var plans=jdbc.query("select revision,plan::text from agent_v2_plan_revision where request_id=? order by revision",
            (rs,n)->new Plan(rs.getInt(1),read(rs.getString(2)),0,false),request);
        var executions=jdbc.query("""
            select id,plan_revision,input_revision,step_id,result::text,source_refs::text from agent_step_execution
            where request_id=? order by plan_revision,input_revision,step_id
            """,(rs,n)->new PublicStep(rs.getString(1),rs.getInt(2),rs.getLong(3),rs.getString(4),read(rs.getString(5)),read(rs.getString(6))),request);
        long inputRevision=jdbc.queryForObject("select request_revision from agent_request where id=?",Long.class,request);
        List<JsonNode> results=new ArrayList<>();Set<String> steps=new HashSet<>();
        for(String id:executionIds) {
            var saved=executions.stream().filter(e->e.id().equals(id)).findFirst().orElse(null);
            check(saved!=null && saved.result()!=null && Set.of("verified","empty","partial").contains(saved.result().path("status").asString()),"Only verified saved executions can be public");
            var result=saved.result();var tool=result.path("outputs").path("toolResult");
            check(tool.isObject() && TOOLS.contains(tool.path("kind").asString())
                && result.path("runRefs").isArray() && tool.path("usedRunRefs").equals(result.path("runRefs"))
                && saved.id().equals(result.path("executionId").asString()) && saved.stepId().equals(result.path("stepId").asString())
                && steps.add(saved.stepId()),"Public result contract or inventory mismatch");
            check(publicReferences(tool,saved.sources()),"Public result Run is outside its frozen source");
            if(currentOnly) check(current(saved,plans,executions,inputRevision),"Execution is no longer valid in the current plan");
            results.add(result);
        }
        return results;
    }
    private boolean publicReferences(JsonNode value,JsonNode sources) {
        if(value.isObject() && value.has("runVersionId")) {
            if(!value.path("runId").isString() || !value.path("runVersionId").isString() || sources==null)return false;
            boolean found=false;
            for(var source:sources) if(source.path("runId").equals(value.path("runId"))
                && source.path("runVersionId").equals(value.path("runVersionId"))) {found=true;break;}
            if(!found)return false;
        }
        if(value.isContainer())for(var child:value)if(!publicReferences(child,sources))return false;
        return true;
    }
    private boolean current(PublicStep saved,List<Plan> plans,List<PublicStep> executions,long inputRevision) {
        var origin=plans.stream().filter(p->p.revision()==saved.planRevision()).findFirst().orElse(null);
        if(origin==null || plans.isEmpty())return false;
        Map<String,JsonNode> original=stepMap(origin.plan());
        Set<String> required=new HashSet<>();
        if(!dependencies(saved.stepId(),original,required,new HashSet<>()))return false;
        for(var plan:plans) if(plan.revision()>=saved.planRevision()) {
            var current=stepMap(plan.plan());
            for(String id:required) if(!original.get(id).equals(current.get(id)))return false;
        }
        for(String id:required) {
            if("await_input".equals(original.get(id).path("kind").asString()) && saved.inputRevision()<inputRevision)return false;
            for(var candidate:executions) if(candidate.stepId().equals(id)
                && (candidate.planRevision()>saved.planRevision() || candidate.inputRevision()>saved.inputRevision()))return false;
        }
        return true;
    }
    private Map<String,JsonNode> stepMap(JsonNode plan) {
        Map<String,JsonNode> result=new HashMap<>();
        for(var step:plan.path("steps")) result.put(step.path("id").asString(),step);
        return result;
    }
    private boolean dependencies(String id,Map<String,JsonNode> steps,Set<String> found,Set<String> visiting) {
        if(found.contains(id))return true;
        var step=steps.get(id);if(step==null || !visiting.add(id))return false;
        for(var dependency:step.path("depends_on")) if(!dependencies(dependency.asString(),steps,found,visiting))return false;
        visiting.remove(id);found.add(id);return true;
    }

    private boolean contains(JsonNode array, JsonNode value) {
        for (var item : array) if (item.equals(value)) return true;
        return false;
    }

    private Map<String, Object> reservation(String key, UUID id, boolean allowed, String valueKey, JsonNode value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put(key, id.toString());
        result.put("callAllowed", allowed);
        result.put(valueKey, value);
        return result;
    }

    private record Plan(int revision, JsonNode plan, long inputRevision, boolean samePlan) {}
    private record Step(UUID id, boolean sameInputs, JsonNode result) {}
    private record Attempt(UUID id, String kind, JsonNode outcome, String deadline, long inputRevision) {}
    private record PublicStep(String id,int planRevision,long inputRevision,String stepId,JsonNode result,JsonNode sources) {}
}
