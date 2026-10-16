package com.kplasma.analysisagent.ingestion;
import java.time.Clock;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
@Configuration @EnableScheduling
public class ImportExecutionConfiguration {
    private final int concurrency;
    public ImportExecutionConfiguration(@Value("${kplasma.worker.concurrency:1}") int concurrency) {
        if(concurrency<1||concurrency>8)throw new IllegalArgumentException("Import concurrency must be between 1 and 8");
        this.concurrency=concurrency;
    }
    @Bean @ConditionalOnMissingBean(Clock.class) Clock registrationClock() {return Clock.systemUTC();}
    @Bean ThreadPoolTaskScheduler taskScheduler() {var scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(concurrency);scheduler.setThreadNamePrefix("import-worker-");scheduler.setContinueExistingPeriodicTasksAfterShutdownPolicy(false);scheduler.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);scheduler.setWaitForTasksToCompleteOnShutdown(false);scheduler.setAwaitTerminationSeconds(30);return scheduler;}
    @Bean SchedulingConfigurer importQueueScheduling(ImportWorker worker,@Value("${kplasma.worker.poll-ms:500}") long idleMillis) {
        if(idleMillis<1)throw new IllegalArgumentException("Import idle polling interval must be positive");
        return tasks->{
            if(concurrency==1){
                tasks.addTriggerTask(worker::poll,context->context.getClock().instant().plusMillis(
                    context.lastCompletion()!=null&&worker.hasBacklog()?0:idleMillis));
            }else for(int i=0;i<concurrency;i++){
                var backlog=new AtomicBoolean();
                tasks.addTriggerTask(()->backlog.set(worker.drain()),context->context.getClock().instant().plusMillis(
                    context.lastCompletion()!=null&&backlog.get()?0:idleMillis));
            }
        };
    }
}
