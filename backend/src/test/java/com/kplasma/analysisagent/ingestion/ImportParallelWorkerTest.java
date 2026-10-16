package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.parser.KPlasmaScalarParser;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@Testcontainers
@SpringBootTest(properties={"kplasma.worker.enabled=true","kplasma.worker.poll-ms=600000","kplasma.worker.drain-limit=2"})
class ImportParallelWorkerTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp();
    @Autowired ImportIntakeService intake; @Autowired SourceStore store;
    @Autowired ImportWorker worker; @Autowired JdbcTemplate jdbc;
    @MockitoSpyBean KPlasmaScalarParser scalars;
    static Path temp(){try{return Files.createTempDirectory("parallel-import-");}catch(Exception e){throw new RuntimeException(e);}}
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r){
        r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);
        r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString);
        r.add("spring.datasource.hikari.maximum-pool-size",()->10);
    }
    @BeforeEach void clear(){reset(scalars);jdbc.execute("truncate import_batch,source_set,run cascade");}
    private BatchView enqueue(int count)throws Exception {return enqueue(count,"parallel-");}
    private BatchView enqueue(int count,String marker)throws Exception {
        List<UploadEntry> entries=new ArrayList<>();List<UploadPart> parts=new ArrayList<>();
        for(int i=0;i<count;i++)for(var entry:SyntheticRunFiles.files(marker+i).entrySet()){
            int power=(1+i%5)*100,pressure=2+(i/5)*2;
            String content=entry.getValue().replace("Powerh=1.e2","Powerh="+power).replace("PowerH = 1.e2","PowerH = "+power)
                    .replace("PRS=2","PRS="+pressure).replace("Pressure = 2 (","Pressure = "+pressure+" (");
            String name="f"+entries.size();Path file=Files.createTempFile(ROOT,"part-",".txt");Files.writeString(file,content);
            entries.add(new UploadEntry(name,"run-"+i+"/"+entry.getKey()));parts.add(new UploadPart(name,file,Files.size(file)));
        }
        return intake.accept(store.stage(new UploadManifest("FOLDER",entries),parts),UUID.randomUUID().toString());
    }
    @ParameterizedTest @ValueSource(ints={2,4,8})
    void concurrentDrainsClaimEachJobOnceAndPublishAccurateProgress(int width)throws Exception {
        var batch=enqueue(width*3);var arrived=new CountDownLatch(width);
        var calls=new AtomicInteger();var active=new AtomicInteger();var peak=new AtomicInteger();
        boolean expectedTransaction=Boolean.parseBoolean(System.getenv("BENCHMARK_PARSING_TRANSACTION"));
        doAnswer(invocation->{
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isEqualTo(expectedTransaction);
            int n=active.incrementAndGet();peak.accumulateAndGet(n,Math::max);
            try{
                if(calls.incrementAndGet()<=width){arrived.countDown();assertThat(arrived.await(15,TimeUnit.SECONDS)).isTrue();}
                return invocation.callRealMethod();
            }finally{active.decrementAndGet();}
        }).when(scalars).parse(any());
        try(var executor=Executors.newFixedThreadPool(width)){
            List<Future<?>> futures=new ArrayList<>();
            for(int i=0;i<width;i++)futures.add(executor.submit(()->{while(worker.drain()) {}}));
            for(var future:futures)future.get(30,TimeUnit.SECONDS);
        }
        assertThat(peak.get()).isEqualTo(width);assertThat(calls.get()).isEqualTo(width*3);
        var result=intake.get(batch.batchId());assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat(result.processedRuns()).isEqualTo(width*3);
        assertThat(result.jobs()).allMatch(j->j.status().equals("READY"));
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(width*3);
        assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(width*3);
    }
    @Test void concurrentAttemptsOfSameJobParseOnlyOnce()throws Exception {
        var batch=enqueue(1);UUID id=UUID.fromString(batch.jobs().getFirst().jobId());
        try(var executor=Executors.newFixedThreadPool(8)){
            var start=new CountDownLatch(1);List<Future<?>> futures=new ArrayList<>();
            for(int i=0;i<8;i++)futures.add(executor.submit(()->{try{start.await();worker.process(id);}catch(InterruptedException e){Thread.currentThread().interrupt();throw new RuntimeException(e);}}));
            start.countDown();for(var f:futures)f.get(15,TimeUnit.SECONDS);
        }
        verify(scalars,times(1)).parse(any());assertThat(intake.get(batch.batchId()).status()).isEqualTo("SUCCESS");
    }
    @Test void oneFailureDoesNotLoseOtherQueuedJobs()throws Exception {
        var batch=enqueue(4);var count=new AtomicInteger();
        doAnswer(invocation->{if(count.incrementAndGet()==1)throw new IllegalStateException("synthetic failure");return invocation.callRealMethod();}).when(scalars).parse(any());
        try(var executor=Executors.newFixedThreadPool(4)){
            List<Future<?>> futures=new ArrayList<>();for(int i=0;i<4;i++)futures.add(executor.submit(()->{while(worker.drain()) {}}));
            for(var f:futures)f.get(15,TimeUnit.SECONDS);
        }
        var result=intake.get(batch.batchId());assertThat(result.status()).isEqualTo("PARTIAL_SUCCESS");
        assertThat(result.processedRuns()).isEqualTo(4);
        assertThat(result.jobs().stream().filter(j->j.status().equals("READY")).count()).isEqualTo(3);
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(3);
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void concurrentAdministratorsPreserveVersionIdentity(boolean changed)throws Exception {
        var first=enqueue(1,"first");var second=enqueue(1,changed?"changed":"first");
        try(var executor=Executors.newFixedThreadPool(2)){
            var start=new CountDownLatch(1);List<Future<?>> futures=new ArrayList<>();
            for(var batch:List.of(first,second))futures.add(executor.submit(()->{
                try{start.await();worker.process(UUID.fromString(batch.jobs().getFirst().jobId()));}
                catch(InterruptedException e){Thread.currentThread().interrupt();throw new RuntimeException(e);}
            }));
            start.countDown();for(var f:futures)f.get(15,TimeUnit.SECONDS);
        }
        assertThat(intake.get(first.batchId()).status()).isEqualTo("SUCCESS");
        assertThat(intake.get(second.batchId()).status()).isEqualTo("SUCCESS");
        assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(changed?2:1);
        assertThat(jdbc.queryForObject("select count(*) from run r join run_version v on v.id=r.current_version_id and v.run_id=r.run_id",Integer.class)).isEqualTo(1);
        if(!changed)assertThat(List.of(intake.get(first.batchId()).jobs().getFirst().status(),intake.get(second.batchId()).jobs().getFirst().status()))
                .containsExactlyInAnyOrder("READY","DUPLICATE");
    }
    @AfterAll static void cleanup(){SourceStore.cleanup(ROOT);}
}
