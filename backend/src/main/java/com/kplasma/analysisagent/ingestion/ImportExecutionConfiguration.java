package com.kplasma.analysisagent.ingestion;
import java.time.Clock;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
@Configuration @EnableScheduling
public class ImportExecutionConfiguration {
    @Bean @ConditionalOnMissingBean(Clock.class) Clock registrationClock() {return Clock.systemUTC();}
    @Bean ThreadPoolTaskScheduler taskScheduler() {var scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(1);scheduler.setThreadNamePrefix("import-worker-");scheduler.setContinueExistingPeriodicTasksAfterShutdownPolicy(false);scheduler.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);scheduler.setWaitForTasksToCompleteOnShutdown(false);scheduler.setAwaitTerminationSeconds(30);return scheduler;}
}
