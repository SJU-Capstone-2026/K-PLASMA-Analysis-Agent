package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
@SpringBootTest(properties={"kplasma.worker.enabled=true","kplasma.worker.poll-ms=600000","kplasma.worker.drain-limit=2"})
class ImportWorkerSchedulingTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp();
    @Autowired ImportIntakeService intake;
    @Autowired SourceStore store;
    @Autowired ImportWorker worker;
    @Autowired JdbcTemplate jdbc;
    static Path temp(){try{return Files.createTempDirectory("upload-schedule-");}catch(Exception e){throw new RuntimeException(e);}}
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);
        r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString);
    }
    @BeforeEach void clear(){jdbc.execute("truncate import_batch,source_set,run cascade");}
    private BatchView enqueue(int count)throws Exception {
        List<UploadEntry> entries=new ArrayList<>();List<UploadPart> parts=new ArrayList<>();
        for(int i=0;i<count;i++)for(var entry:SyntheticRunFiles.files("source-"+i).entrySet()){
            String part="f"+entries.size();Path path=Files.createTempFile(ROOT,"part-",".txt");Files.writeString(path,entry.getValue());
            entries.add(new UploadEntry(part,"run-"+i+"/"+entry.getKey()));parts.add(new UploadPart(part,path,Files.size(path)));
        }
        return intake.accept(store.stage(new UploadManifest("FOLDER",entries),parts),UUID.randomUUID().toString());
    }
    @Test void onePollDrainsMoreThanOneCommittedJob()throws Exception {
        var batch=enqueue(2);worker.poll();
        assertThat(intake.get(batch.batchId()).processedRuns()).isEqualTo(2);
    }
    @Test void drainIsBoundedAndTheFollowingPollProcessesTheRemainder()throws Exception {
        var batch=enqueue(3);worker.poll();
        assertThat(intake.get(batch.batchId()).processedRuns()).isEqualTo(2);
        worker.poll();
        assertThat(intake.get(batch.batchId()).status()).isEqualTo("SUCCESS");
        assertThat(intake.get(batch.batchId()).processedRuns()).isEqualTo(3);
    }
    @Test void triggerReschedulesBacklogImmediatelyButWaitsForAnEmptyQueue()throws Exception {
        var batch=enqueue(3);worker.poll();assertThat(worker.hasBacklog()).isTrue();
        var tasks=new org.springframework.scheduling.config.ScheduledTaskRegistrar();
        new ImportExecutionConfiguration(1).importQueueScheduling(worker,500).configureTasks(tasks);
        var trigger=tasks.getTriggerTaskList().getFirst().getTrigger();
        var now=java.time.Instant.parse("2026-10-15T00:00:00Z");
        var context=new org.springframework.scheduling.support.SimpleTriggerContext(java.time.Clock.fixed(now,java.time.ZoneOffset.UTC));
        assertThat(trigger.nextExecution(context)).isEqualTo(now.plusMillis(500));
        context.update(now,now,now);
        assertThat(trigger.nextExecution(context)).isEqualTo(now);
        worker.poll();assertThat(worker.hasBacklog()).isFalse();
        assertThat(intake.get(batch.batchId()).processedRuns()).isEqualTo(3);
        assertThat(trigger.nextExecution(context)).isEqualTo(now.plusMillis(500));
    }
    @Test void parallelSlotsHaveIndependentBacklogAndBoundedThreads() {
        var mocked=org.mockito.Mockito.mock(ImportWorker.class);
        org.mockito.Mockito.when(mocked.drain()).thenReturn(true,false);
        var config=new ImportExecutionConfiguration(8);
        assertThat(config.taskScheduler().getPoolSize()).isEqualTo(8);
        var tasks=new org.springframework.scheduling.config.ScheduledTaskRegistrar();
        config.importQueueScheduling(mocked,500).configureTasks(tasks);
        assertThat(tasks.getTriggerTaskList()).hasSize(8);
        var now=java.time.Instant.parse("2026-10-16T00:00:00Z");
        var context=new org.springframework.scheduling.support.SimpleTriggerContext(java.time.Clock.fixed(now,java.time.ZoneOffset.UTC));
        context.update(now,now,now);
        tasks.getTriggerTaskList().get(0).getRunnable().run();
        tasks.getTriggerTaskList().get(1).getRunnable().run();
        assertThat(tasks.getTriggerTaskList().get(0).getTrigger().nextExecution(context)).isEqualTo(now);
        assertThat(tasks.getTriggerTaskList().get(1).getTrigger().nextExecution(context)).isEqualTo(now.plusMillis(500));
        assertThatThrownBy(()->new ImportExecutionConfiguration(0)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->new ImportExecutionConfiguration(9)).isInstanceOf(IllegalArgumentException.class);
    }
    @AfterAll static void cleanup(){SourceStore.cleanup(ROOT);}
}
