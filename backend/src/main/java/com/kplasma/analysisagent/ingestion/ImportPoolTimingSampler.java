package com.kplasma.analysisagent.ingestion;

import com.zaxxer.hikari.HikariDataSource;
import jakarta.annotation.*;
import java.sql.SQLException;
import java.util.concurrent.*;
import javax.sql.DataSource;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Opt-in in-process observation; never borrows a connection or shares the import worker. */
@Component
@ConditionalOnProperty(name="kplasma.import-timing.enabled",havingValue="true")
public class ImportPoolTimingSampler {
    private final HikariDataSource source;
    private ScheduledExecutorService sampler;
    public ImportPoolTimingSampler(DataSource source)throws SQLException{this.source=source.unwrap(HikariDataSource.class);}
    @PostConstruct void start(){
        sampler=Executors.newSingleThreadScheduledExecutor(task->{var t=new Thread(task,"import-pool-observer");t.setDaemon(true);return t;});
        sampler.scheduleWithFixedDelay(this::sample,0,100,TimeUnit.MILLISECONDS);
    }
    private void sample(){
        var pool=source.getHikariPoolMXBean();if(pool==null)return;
        try(var trace=ImportTimingRecorder.trace("pool",source.getPoolName())){
            trace.field("active",pool.getActiveConnections());trace.field("idle",pool.getIdleConnections());
            trace.field("total",pool.getTotalConnections());trace.field("pending",pool.getThreadsAwaitingConnection());
            trace.field("maximum",source.getMaximumPoolSize());trace.field("minimumIdle",source.getMinimumIdle());
            trace.field("connectionTimeoutMs",source.getConnectionTimeout());
        }
    }
    @PreDestroy void stop(){if(sampler!=null)sampler.shutdownNow();}
}
