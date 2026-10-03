package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto;
import com.kplasma.analysisagent.parser.*;
import com.kplasma.analysisagent.run.*;
import java.nio.file.*;
import java.util.*;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

/** One bounded scheduler consumes committed jobs; each Run publishes atomically. */
@Service
public class ImportWorker {
    private record Job(UUID id,UUID batch,UUID source,String root,boolean reprocess) {}
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final SourceStore store;
    private final ImportRepository imports;
    private final RunRepository runs;
    private final RunRegistrationService registration;
    private final KPlasmaScalarParser scalars;
    private final KPlasmaGraphParser graphs;
    private final ImportRecovery recovery;
    private final TransactionTemplate transactions;
    private final boolean enabled;
    public ImportWorker(JdbcTemplate jdbc,ObjectMapper mapper,SourceStore store,ImportRepository imports,RunRepository runs,
            RunRegistrationService registration,KPlasmaScalarParser scalars,KPlasmaGraphParser graphs,ImportRecovery recovery,
            PlatformTransactionManager manager,@Value("${kplasma.worker.enabled:true}") boolean enabled) {
        this.jdbc=jdbc;this.mapper=mapper;this.store=store;this.imports=imports;this.runs=runs;this.registration=registration;
        this.scalars=scalars;this.graphs=graphs;this.recovery=recovery;this.transactions=new TransactionTemplate(manager);this.enabled=enabled;
    }
    @Scheduled(fixedDelayString="${kplasma.worker.poll-ms:500}",initialDelayString="${kplasma.worker.poll-ms:500}")
    public void poll() {
        if(!enabled||!recovery.ready())return;
        var ids=jdbc.query("select id from import_job where status='QUEUED' order by created_at,id limit 1",(rs,n)->rs.getObject(1,UUID.class));
        if(!ids.isEmpty())process(ids.getFirst());
    }
    public void process(UUID id) {
        Job job=transactions.execute(tx->{
            var jobs=jdbc.query("select id,batch_id,source_id,source_root,reprocess from import_job where id=? and status='QUEUED' for update skip locked",(rs,n)->new Job(rs.getObject(1,UUID.class),rs.getObject(2,UUID.class),rs.getObject(3,UUID.class),rs.getString(4),rs.getBoolean(5)),id);
            if(jobs.isEmpty())return null;
            jdbc.update("update import_job set status='PROCESSING',updated_at=now() where id=?",id);
            refresh(jobs.getFirst().batch());return jobs.getFirst();
        });
        if(job==null)return;
        try {
            // Serialize attempts for a source across public process callers as well as the single scheduler.
            transactions.executeWithoutResult(tx->{
                jdbc.queryForList("select id from source_set where id=? for update",job.source());
                RunRef previous=job.reprocess()?null:runs.sourceVersion(job.source());
                if(previous!=null) {finish(job,"DUPLICATE",previous,null,List.of());return;}
                var source=load(job);
                var scalar=scalars.parse(source);var graph=graphs.parse(source,scalar);
                var ref=registration.register(source,scalar,graph);
                finish(job,"READY",ref,null,List.of());
            });
        } catch(ParseFailure failure) {
            var details=Map.<String,Object>of("path",failure.path(),"line",failure.line());
            failure(job,failure.status(),failure.getMessage(),List.of(new WorkspaceDto.Error(failure.status(),failure.getMessage(),failure.field(),details,UUID.randomUUID().toString())));
        } catch(RuntimeException failure) {
            // The exception may contain storage paths or SQL input, so expose only a stable safe diagnostic.
            LoggerFactory.getLogger(ImportWorker.class).warn("Import job {} failed ({})",id,failure.getClass().getSimpleName());
            failure(job,"PARSE_FAILED","Import processing failed; originals retained for reprocessing",List.of(new WorkspaceDto.Error("PROCESSING_FAILED","Import processing failed; originals retained for reprocessing",null,null,UUID.randomUUID().toString())));
        }
    }
    private StoredSource load(Job job) {
        Map<String,StoredBatch.File> files=new HashMap<>();
        jdbc.query("select relative_path,storage_path,size,sha256,kind from source_file where source_id=?",rs->{
            String path=rs.getString(1);Path physical=store.root().resolve(rs.getString(2)).normalize();
            if(!physical.startsWith(store.root().toAbsolutePath().normalize()))throw new IllegalStateException("Invalid retained original location");
            files.put(path,new StoredBatch.File(path,physical,rs.getLong(3),rs.getString(4),rs.getString(5)));
        },job.source());
        String hash=jdbc.queryForObject("select sha256 from source_set where id=?",String.class,job.source());
        return new StoredSource(job.source(),job.root(),files,hash);
    }
    private void failure(Job job,String status,String reason,List<WorkspaceDto.Error> errors) {transactions.executeWithoutResult(tx->finish(job,status,null,reason,errors));}
    private void finish(Job job,String status,RunRef ref,String reason,List<WorkspaceDto.Error> errors) {
        jdbc.update("update import_job set status=?,run_id=?,run_version_id=?,reason=?,errors=?::jsonb,updated_at=now() where id=?",status,ref==null?null:ref.runId(),ref==null?null:UUID.fromString(ref.runVersionId()),reason,mapper.writeValueAsString(errors),job.id());
        refresh(job.batch());
    }
    void refresh(UUID batch) {
        jdbc.queryForList("select id from import_batch where id=? for update",batch);
        var counts=jdbc.queryForMap("select count(*) filter (where status in ('READY','DUPLICATE')) good, count(*) filter (where status not in ('QUEUED','PROCESSING')) done,count(*) filter (where status='PROCESSING') active,count(*) total from import_job where batch_id=?",batch);
        long good=((Number)counts.get("good")).longValue(),done=((Number)counts.get("done")).longValue(),total=((Number)counts.get("total")).longValue(),active=((Number)counts.get("active")).longValue();
        String status=done==total?(good==total?"SUCCESS":good>0?"PARTIAL_SUCCESS":"FAILED"):active>0||done>0?"PROCESSING":"QUEUED";
        jdbc.update("update import_batch set status=?,processed_runs=? where id=?",status,(int)done,batch);
    }
    public BatchView reprocess(UUID id,String key) {
        if(key==null||key.isBlank()||key.length()>200)throw IntakeException.invalid("A valid idempotency key is required");
        return transactions.execute(tx->{
            imports.lockIntake();
            var replay=jdbc.queryForList("select original_job_id,batch_id from reprocess_idempotency where idempotency_key=?",key);
            if(!replay.isEmpty()) {
                var row=replay.getFirst();if(!id.equals(row.get("original_job_id")))throw new IntakeException("IDEMPOTENCY_CONFLICT",409,"idempotency key was used for a different job");
                return imports.get((UUID)row.get("batch_id"));
            }
            var original=jdbc.queryForList("select batch_id,source_id,source_root,status from import_job where id=? for update",id);
            if(original.isEmpty())throw new IntakeException("NOT_FOUND",404,"Import job not found");
            var row=original.getFirst();
            if(Set.of("QUEUED","PROCESSING").contains(row.get("status")))throw new IntakeException("JOB_IN_PROGRESS",409,"Import job is still processing");
            UUID batch=UUID.randomUUID(),job=UUID.randomUUID();
            String prefix=directoryPrefix((String)row.get("source_root"));
            long bytes=jdbc.queryForObject("select coalesce(sum(size),0) from import_batch_file where batch_id=? and starts_with(relative_path,?)",Long.class,row.get("batch_id"),prefix);
            jdbc.update("insert into import_batch(id,status,received_bytes,total_bytes,total_runs) values (?,'QUEUED',0,?,1)",batch,bytes);
            jdbc.update("insert into import_job(id,batch_id,source_id,source_root,status,reprocess) values (?,?,?,?,'QUEUED',true)",job,batch,row.get("source_id"),row.get("source_root"));
            jdbc.update("insert into import_batch_file(batch_id,relative_path,size,sha256,kind,storage_path) select ?,relative_path,size,sha256,kind,storage_path from import_batch_file where batch_id=? and starts_with(relative_path,?)",batch,row.get("batch_id"),prefix);
            jdbc.update("insert into reprocess_idempotency(idempotency_key,original_job_id,batch_id) values (?,?,?)",key,id,batch);
            return imports.get(batch);
        });
    }
    private String directoryPrefix(String root) {return root.isEmpty()||root.equals(".")?"":root.endsWith("/")?root:root+"/";}
    public List<ManifestFile> files(UUID id) {
        var jobs=jdbc.queryForList("select batch_id,source_root from import_job where id=?",id);
        if(jobs.isEmpty())throw new IntakeException("NOT_FOUND",404,"Import job not found");
        var job=jobs.getFirst();
        return jdbc.query("select relative_path,kind,size,sha256 from import_batch_file where batch_id=? and starts_with(relative_path,?) order by relative_path",(rs,n)->new ManifestFile(rs.getString(1),rs.getString(2),rs.getLong(3),rs.getString(4)),job.get("batch_id"),directoryPrefix((String)job.get("source_root")));
    }
    public List<JobView> jobs() {
        return jdbc.query("select id,run_id,run_version_id,status,reason,errors from import_job order by created_at,id",(rs,n)->new JobView(rs.getString(1),rs.getString(2),rs.getString(3),rs.getString(4),rs.getString(5),mapper.readValue(rs.getString(6),new tools.jackson.core.type.TypeReference<List<WorkspaceDto.Error>>(){})));
    }
}
