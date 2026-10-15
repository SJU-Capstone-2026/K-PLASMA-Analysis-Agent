package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.parser.KPlasmaScalarParser;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.*;
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

@Testcontainers @SpringBootTest(properties="kplasma.worker.enabled=false")
class ImportPublicationConcurrencyTest {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp();
    @Autowired ImportIntakeService intake;@Autowired SourceStore store;@Autowired ImportWorker worker;@Autowired JdbcTemplate jdbc;
    @MockitoSpyBean KPlasmaScalarParser scalars;
    static Path temp(){try{return Files.createTempDirectory("upload-publish-");}catch(Exception e){throw new RuntimeException(e);}}
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);
        r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString);
    }
    @BeforeEach void clear(){jdbc.execute("truncate import_batch,source_set,run cascade");}
    private BatchView enqueue(String marker)throws Exception {
        List<UploadEntry> entries=new ArrayList<>();List<UploadPart> parts=new ArrayList<>();
        for(var entry:SyntheticRunFiles.files(marker).entrySet()){
            String name="f"+entries.size();Path file=Files.createTempFile(ROOT,"part-",".txt");Files.writeString(file,entry.getValue());
            entries.add(new UploadEntry(name,"run/"+entry.getKey()));parts.add(new UploadPart(name,file,Files.size(file)));
        }
        return intake.accept(store.stage(new UploadManifest("FOLDER",entries),parts),UUID.randomUUID().toString());
    }
    @Test void parserRunsWithoutAnOpenDatabaseTransaction()throws Exception {
        doAnswer(invocation->{
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).as("file parsing must release the DB transaction").isFalse();
            return invocation.callRealMethod();
        }).when(scalars).parse(any());
        var batch=enqueue("outside-tx");worker.process(UUID.fromString(batch.jobs().getFirst().jobId()));
        assertThat(intake.get(batch.batchId()).status()).isEqualTo("SUCCESS");
    }
    @Test void twoParsersOfTheSameSourcePublishExactlyOneVersion()throws Exception {
        var first=enqueue("shared");var second=enqueue("shared");
        var reached=new CountDownLatch(1);var release=new CountDownLatch(1);var calls=new AtomicInteger();
        doAnswer(invocation->{
            if(calls.incrementAndGet()==1){reached.countDown();if(!release.await(15,TimeUnit.SECONDS))throw new IllegalStateException("test barrier timeout");}
            return invocation.callRealMethod();
        }).when(scalars).parse(any());
        try(var executor=Executors.newFixedThreadPool(2)){
            var f=executor.submit(()->worker.process(UUID.fromString(first.jobs().getFirst().jobId())));
            try{
                assertThat(reached.await(10,TimeUnit.SECONDS)).isTrue();
                var s=executor.submit(()->worker.process(UUID.fromString(second.jobs().getFirst().jobId())));
                s.get(10,TimeUnit.SECONDS);
            }finally{release.countDown();}
            f.get(10,TimeUnit.SECONDS);
        }
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(1);
        assertThat(List.of(intake.get(first.batchId()).jobs().getFirst().status(),intake.get(second.batchId()).jobs().getFirst().status()))
            .containsExactlyInAnyOrder("READY","DUPLICATE");
    }
    @AfterAll static void cleanup(){SourceStore.cleanup(ROOT);}
}
