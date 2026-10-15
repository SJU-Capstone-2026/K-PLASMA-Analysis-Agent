package com.kplasma.analysisagent.ingestion;
import java.time.Clock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.SchedulingConfigurer;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
@Configuration @EnableScheduling
public class ImportExecutionConfiguration {
    @Bean @ConditionalOnMissingBean(Clock.class) Clock registrationClock() {return Clock.systemUTC();}
    @Bean ThreadPoolTaskScheduler taskScheduler() {var scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(1);scheduler.setThreadNamePrefix("import-worker-");scheduler.setContinueExistingPeriodicTasksAfterShutdownPolicy(false);scheduler.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);scheduler.setWaitForTasksToCompleteOnShutdown(false);scheduler.setAwaitTerminationSeconds(30);return scheduler;}
    @Bean SchedulingConfigurer importQueueScheduling(ImportWorker worker,@Value("${kplasma.worker.poll-ms:500}") long idleMillis) {
        if(idleMillis<1)throw new IllegalArgumentException("Import idle polling interval must be positive");
        return tasks->tasks.addTriggerTask(worker::poll,context->context.getClock().instant().plusMillis(
            context.lastCompletion()!=null&&worker.hasBacklog()?0:idleMillis));
    }
}
