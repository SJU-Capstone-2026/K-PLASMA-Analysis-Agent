package com.kplasma.analysisagent.ingestion;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Startup recovery finishes before polling, and cleanup never follows storage symlinks. */
@Component
public class ImportRecovery implements SmartInitializingSingleton {
    private final JdbcTemplate jdbc;
    private final ImportRepository imports;
    private final SourceStore store;
    private final StorageGarbageCollector garbage;
    private final TransactionTemplate transactions;
    private volatile boolean ready;
    public ImportRecovery(JdbcTemplate jdbc,ImportRepository imports,SourceStore store,StorageGarbageCollector garbage,PlatformTransactionManager manager) {this.jdbc=jdbc;this.imports=imports;this.store=store;this.garbage=garbage;this.transactions=new TransactionTemplate(manager);}
    public boolean ready() {return ready;}
    @Override public void afterSingletonsInstantiated() {recover();}
    public void recover() {
        transactions.executeWithoutResult(tx->{
            imports.lockIntake();
            jdbc.update("update import_job set status='INTERRUPTED',reason='Processing interrupted; originals retained for reprocessing',updated_at=now() where status='PROCESSING'");
            jdbc.update("""
                update import_batch b set processed_runs=c.done, status=case when c.done=c.total then
                    case when c.good=c.total then 'SUCCESS' when c.good>0 then 'PARTIAL_SUCCESS' else 'FAILED' end
                    when c.active>0 or c.done>0 then 'PROCESSING' else 'QUEUED' end
                from (select batch_id,count(*) total,count(*) filter (where status not in ('QUEUED','PROCESSING'))::int done,
                    count(*) filter (where status in ('READY','DUPLICATE')) good,count(*) filter (where status='PROCESSING') active
                    from import_job group by batch_id) c where b.id=c.batch_id
                """);
            garbage.collect();
            cleanup("staging",Set.of());cleanup("uploads",Set.of());
        });
        ready=true;
    }
    private void cleanup(String parent,Set<String> known) {
        Path directory=store.root().resolve(parent);
        if(!Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)||Files.isSymbolicLink(directory))return;
        try(var paths=Files.list(directory)) {
            for(var path:paths.toList()) {
                if(known.contains(path.getFileName().toString())||Files.isSymbolicLink(path))continue;
                if(Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS))SourceStore.cleanup(path);
            }
        } catch(IOException e) {throw new java.io.UncheckedIOException("Import recovery storage unavailable",e);}
    }
}
