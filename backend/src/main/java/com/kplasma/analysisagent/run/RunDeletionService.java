package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDeletionDto.*;
import com.kplasma.analysisagent.ingestion.*;
import java.util.*;
import java.util.regex.Pattern;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunDeletionService {
    private static final Pattern RUN_ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_-]{0,63}");
    private record Job(UUID id, UUID batch, String root) {}
    private record CurrentReferences(String active, String candidates) {}
    private final JdbcTemplate jdbc;
    private final NamedParameterJdbcTemplate named;
    private final ImportRepository imports;
    private final StorageGarbageCollector garbage;
    private final ObjectMapper mapper;
    private final TransactionTemplate transactions;

    public RunDeletionService(JdbcTemplate jdbc, ImportRepository imports, StorageGarbageCollector garbage,
            ObjectMapper mapper, PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        this.named = new NamedParameterJdbcTemplate(jdbc);
        this.imports = imports;
        this.garbage = garbage;
        this.mapper = mapper;
        this.transactions = new TransactionTemplate(manager);
    }

    public Result delete(Request request) {
        List<String> ids = validate(request);
        List<String> deleted = transactions.execute(tx -> deleteRegistered(ids));
        // Never remove bytes before the owning database transaction has committed.
        boolean pending;
        try {
            pending = Boolean.TRUE.equals(transactions.execute(tx -> {
                imports.lockIntake();
                return garbage.collect();
            }));
        } catch (RuntimeException failure) {
            LoggerFactory.getLogger(RunDeletionService.class).warn("Run deletion committed; managed original cleanup will retry ({})", failure.getClass().getSimpleName());
            pending = true;
        }
        return new Result(deleted, pending);
    }

    private List<String> validate(Request request) {
        if (request == null || request.runIds() == null || request.runIds().isEmpty() || request.runIds().size() > 1000)
            throw new IntakeException("INVALID_RUN_SELECTION", 400, "삭제할 Run ID를 1개 이상 1,000개 이하로 지정해 주세요.");
        Set<String> ids = new LinkedHashSet<>();
        for (Object value : request.runIds()) {
            if (!(value instanceof String id) || !RUN_ID.matcher(id).matches())
                throw new IntakeException("INVALID_RUN_SELECTION", 400, "Run ID는 1~64자의 영문·숫자·밑줄·하이픈 문자열이어야 합니다.");
            ids.add(id);
        }
        return List.copyOf(ids);
    }

    private List<String> deleteRegistered(List<String> requested) {
        imports.lockIntake();
        jdbc.queryForList("select id from workspace where id=1 for update");
        // A queued source has no Run id yet and could publish the same Run after deletion.
        if (Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from import_job where status in ('QUEUED','PROCESSING'))", Boolean.class)))
            throw new IntakeException("IMPORT_IN_PROGRESS", 409, "등록 또는 재처리가 진행 중입니다. 모든 작업이 끝난 뒤 삭제해 주세요.");
        var parameters = Map.of("ids", requested);
        List<String> deleted = named.queryForList("select run_id from run where run_id in (:ids) order by run_id", parameters, String.class);
        if (deleted.isEmpty()) return List.of();
        rejectReferences(new HashSet<>(deleted));
        releaseCurrentReferences(new HashSet<>(deleted));
        var selected = Map.of("ids", deleted);
        List<UUID> sources = named.queryForList("select distinct source_id from run_version where run_id in (:ids)", selected, UUID.class);
        List<Job> jobs = named.query("select id,batch_id,source_root from import_job where run_id in (:ids) or run_version_id in (select id from run_version where run_id in (:ids))", selected,
                (rs, n) -> new Job(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getString(3)));
        removeJobs(jobs);
        named.update("update run set current_version_id=null where run_id in (:ids)", selected);
        named.update("delete from run_version where run_id in (:ids)", selected);
        named.update("delete from run where run_id in (:ids)", selected);
        if (!sources.isEmpty()) {
            var candidates = Map.of("sources", sources);
            List<UUID> unowned = named.queryForList("select id from source_set s where id in (:sources) and not exists(select 1 from run_version v where v.source_id=s.id) and not exists(select 1 from import_job j where j.source_id=s.id)", candidates, UUID.class);
            if (!unowned.isEmpty()) {
                named.update("delete from source_file where source_id in (:sources)", Map.of("sources", unowned));
                named.update("delete from source_set where id in (:sources)", Map.of("sources", unowned));
            }
        }
        return List.copyOf(deleted);
    }

    private void removeJobs(List<Job> jobs) {
        if (jobs.isEmpty()) return;
        var ids = Map.of("jobs", jobs.stream().map(Job::id).toList());
        named.update("delete from reprocess_idempotency where original_job_id in (:jobs)", ids);
        named.update("delete from import_job where id in (:jobs)", ids);
        for (Job job : jobs) {
            String prefix = job.root().isEmpty() || job.root().equals(".") ? "" : job.root().endsWith("/") ? job.root() : job.root() + "/";
            jdbc.update("""
                delete from import_batch_file f where batch_id=? and starts_with(relative_path,?)
                and not exists(select 1 from import_job j where j.batch_id=f.batch_id and
                    (j.source_root in ('','.') or starts_with(f.relative_path,rtrim(j.source_root,'/')||'/')))
                """, job.batch(), prefix);
        }
        for (UUID batch : jobs.stream().map(Job::batch).distinct().toList()) {
            jdbc.update("delete from import_batch_file where batch_id=? and not exists(select 1 from import_job where batch_id=?)", batch, batch);
            // Empty batches and their upload keys are tombstones: an old upload retry cannot restore a deleted Run.
            jdbc.update("""
                update import_batch set total_runs=c.total,processed_runs=c.done,
                    status=case when c.good=c.total then 'SUCCESS' when c.good>0 then 'PARTIAL_SUCCESS' else 'FAILED' end,
                    total_bytes=f.bytes,received_bytes=least(received_bytes,f.bytes)
                from (select count(*)::int total,count(*) filter(where status not in ('QUEUED','PROCESSING'))::int done,
                    count(*) filter(where status in ('READY','DUPLICATE'))::int good from import_job where batch_id=?) c,
                    (select coalesce(sum(size),0) bytes from import_batch_file where batch_id=?) f
                where id=?
                """, batch, batch, batch);
        }
    }

    private void rejectReferences(Set<String> ids) {
        Map<String, Set<String>> uses = new TreeMap<>();
        for (String json : jdbc.queryForList("select record::text from decision", String.class))
            collectReferences(mapper.readTree(json), ids, "판단 기록", uses);
        if (!uses.isEmpty()) {
            String message = String.join(", ", uses.entrySet().stream().map(e -> e.getKey() + " (" + String.join("·", e.getValue()) + ")").toList());
            throw new IntakeException("RUN_IN_USE", 409, "판단 기록에서 사용 중인 Run은 삭제할 수 없습니다: " + message + ". 판단 기록을 초기화하거나 Run을 유지해 주세요.");
        }
    }

    private void releaseCurrentReferences(Set<String> ids) {
        CurrentReferences current = jdbc.queryForObject("select active_run::text,candidate_reference::text from workspace where id=1",
                (rs, n) -> new CurrentReferences(rs.getString(1), rs.getString(2)));
        boolean active = current != null && containsReference(current.active(), ids);
        boolean candidates = current != null && containsReference(current.candidates(), ids);
        if (active || candidates) jdbc.update("""
            update workspace set
                active_run=case when ? then null else active_run end,
                candidate_reference=case when ? then null else candidate_reference end,
                revision=revision+1
            where id=1
            """, active, candidates);
    }

    private boolean containsReference(String json, Set<String> ids) {
        if (json == null) return false;
        Map<String, Set<String>> found = new HashMap<>();
        collectReferences(mapper.readTree(json), ids, "현재 참조", found);
        return !found.isEmpty();
    }

    private void collectReferences(JsonNode node, Set<String> ids, String kind, Map<String, Set<String>> uses) {
        if (node == null) return;
        if (node.isObject()) {
            JsonNode id = node.get("runId");
            if (id != null && id.isString() && ids.contains(id.stringValue())) uses.computeIfAbsent(id.stringValue(), ignored -> new TreeSet<>()).add(kind);
        }
        if (node.isContainer()) for (JsonNode child : node) collectReferences(child, ids, kind, uses);
    }
}
