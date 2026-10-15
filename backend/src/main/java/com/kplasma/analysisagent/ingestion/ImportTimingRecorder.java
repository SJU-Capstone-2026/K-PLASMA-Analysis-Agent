package com.kplasma.analysisagent.ingestion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.function.LongSupplier;
import tools.jackson.databind.ObjectMapper;

/** Opt-in local measurements. Timings are nested intervals, never additive counters. */
public final class ImportTimingRecorder implements AutoCloseable {
    private static final ImportTimingRecorder SYSTEM=new ImportTimingRecorder(
        Boolean.getBoolean("kplasma.import-timing.enabled")
            ? Path.of(Objects.requireNonNull(System.getProperty("kplasma.import-timing.file"),"Timing file required")) : null,
        System::nanoTime);
    private final LongSupplier clock;
    private final BufferedWriter writer;
    private final ObjectMapper mapper=new ObjectMapper();
    private final ThreadLocal<Context> current=new ThreadLocal<>();
    private record Context(String kind,String id,String[] batch) {}
    ImportTimingRecorder(Path path,LongSupplier clock) {
        this.clock=clock;
        try {
            if(path==null)writer=null;
            else {Files.createDirectories(path.toAbsolutePath().getParent());writer=Files.newBufferedWriter(path,StandardCharsets.UTF_8,StandardOpenOption.CREATE,StandardOpenOption.APPEND);}
        } catch(IOException e) {throw new UncheckedIOException("Cannot open import timing output",e);}
    }
    public static Scope trace(String kind,String id) {return SYSTEM.begin(kind,id);}
    public static Scope span(String phase) {return SYSTEM.measure(phase);}
    public static void batch(String id) {SYSTEM.bindBatch(id);}
    public static void mark(String phase) {try(var ignored=span(phase)) {/* point event */}}
    public static <T> T call(String phase,java.util.function.Supplier<T> work) {
        try(var ignored=span(phase)){return work.get();}
    }
    public static <T> T transaction(String phase,org.springframework.transaction.support.TransactionTemplate tx,
            org.springframework.transaction.support.TransactionCallback<T> work) {
        try(var ignored=span(phase)){return tx.execute(work);}
    }
    public static void inTransaction(String phase,org.springframework.transaction.support.TransactionTemplate tx,
            java.util.function.Consumer<org.springframework.transaction.TransactionStatus> work) {
        try(var ignored=span(phase)){tx.executeWithoutResult(work);}
    }
    public static void committed(String phase) {
        if(SYSTEM.writer==null)return;
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
            new org.springframework.transaction.support.TransactionSynchronization() {
                @Override public void afterCommit(){mark(phase);}
            });
    }
    Scope begin(String kind,String id) {
        if(writer==null)return Scope.NOOP;
        var previous=current.get();var context=new Context(kind,id,new String[]{""});
        current.set(context);return new Scope(this,context,kind,clock.getAsLong(),previous,true);
    }
    void bindBatch(String id) {var context=current.get();if(context!=null)context.batch()[0]=id;}
    Scope measure(String phase) {
        var context=current.get();
        return writer==null||context==null?Scope.NOOP:new Scope(this,context,phase,clock.getAsLong(),null,false);
    }
    private synchronized void emit(Scope scope,long end) {
        try {
            var event=new LinkedHashMap<String,Object>();
            event.put("kind",scope.context.kind());event.put("id",scope.context.id());
            event.put("batchId",scope.context.batch()[0]);event.put("phase",scope.phase);
            event.put("startNs",scope.start);event.put("endNs",end);event.put("bytes",scope.bytes);
            writer.write(mapper.writeValueAsString(event));writer.newLine();
            if(scope.root)writer.flush();
        } catch(IOException e) {
            // Observability must not change registration outcome. The harness rejects missing events.
            org.slf4j.LoggerFactory.getLogger(ImportTimingRecorder.class).warn("Import timing output unavailable");
        }
    }
    @Override public synchronized void close() {try{if(writer!=null)writer.close();}catch(IOException e){throw new UncheckedIOException(e);}}
    public static final class Scope implements AutoCloseable {
        private static final Scope NOOP=new Scope(null,null,"",0,null,false);
        private final ImportTimingRecorder recorder;private final Context context,previous;
        private final String phase;private final long start;private final boolean root;
        private long bytes;private boolean closed;
        private Scope(ImportTimingRecorder recorder,Context context,String phase,long start,Context previous,boolean root) {
            this.recorder=recorder;this.context=context;this.phase=phase;this.start=start;this.previous=previous;this.root=root;
        }
        public void bytes(long value) {if(recorder!=null)bytes+=value;}
        @Override public void close() {
            if(recorder==null||closed)return;closed=true;
            recorder.emit(this,recorder.clock.getAsLong());
            if(root) {if(previous==null)recorder.current.remove();else recorder.current.set(previous);}
        }
    }
}
