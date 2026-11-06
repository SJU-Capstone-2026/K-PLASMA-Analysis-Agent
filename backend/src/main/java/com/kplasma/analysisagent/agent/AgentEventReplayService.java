package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.v2.V2ExecutionRepository;
import com.kplasma.analysisagent.ingestion.IntakeException;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class AgentEventReplayService {
    private final AgentRequestRepository requests;
    private final AgentPublicEvents events;
    private final V2ExecutionRepository executions;
    private final AgentPublicResultProjection projection;
    private final JdbcTemplate jdbc;
    private final org.springframework.transaction.support.TransactionTemplate transaction;
    private final ExecutorService subscriptions=Executors.newVirtualThreadPerTaskExecutor();
    public AgentEventReplayService(AgentRequestRepository requests,AgentPublicEvents events,V2ExecutionRepository executions,
            AgentPublicResultProjection projection,JdbcTemplate jdbc,org.springframework.transaction.PlatformTransactionManager manager) {
        this.requests=requests;this.events=events;this.executions=executions;this.projection=projection;this.jdbc=jdbc;
        this.transaction=new org.springframework.transaction.support.TransactionTemplate(manager);
    }
    public record Page(List<Map<String,Object>> events,long lastEventSeq,String status,long requestRevision,
        long workspaceEpoch,long conversationEpoch,boolean hasMore) {
        boolean terminal() {return Set.of("COMPLETED","FAILED","CANCELLED","NEEDS_INPUT").contains(status);}
    }
    private AgentRequestRepository.Row readable(UUID id) {
        var row=requests.get(id,true);
        boolean current=Boolean.TRUE.equals(jdbc.queryForObject("""
            select exists(select 1 from workspace w join workspace_conversation c on c.workspace_epoch=w.workspace_epoch
                where w.id=1 and c.workspace_epoch=? and c.conversation_epoch=?)
            """,Boolean.class,row.workspaceEpoch(),row.conversationEpoch()));
        if(row.question()==null || !current)throw new IntakeException("NOT_FOUND",404,"Agent request content is no longer available");
        return row;
    }
    public Page page(UUID id,long after) {
        // The row lock lasts only for this page, never for an SSE send or its polling interval.
        return transaction.execute(status->{
            var row=readable(id);
            if(after<0 || after>row.lastEventSeq())throw new IntakeException("INVALID_EVENT_CURSOR",400,"Event cursor is outside this request");
            var items=events.page(id,after,row.lastEventSeq(),256);
            long delivered=items.isEmpty()?after:((Number)items.getLast().get("seq")).longValue();
            return new Page(items,row.lastEventSeq(),row.status(),row.revision(),row.workspaceEpoch(),row.conversationEpoch(),delivered<row.lastEventSeq());
        });
    }
    @Transactional public Map<String,Object> results(UUID id,long revision) {
        var row=readable(id);
        if(revision<1 || revision>row.lastEventSeq())throw new IntakeException("NOT_FOUND",404,"Public result version not found");
        var binding=events.resultBinding(id,revision);
        @SuppressWarnings("unchecked") var ids=(List<String>)binding.get("executionIds");
        return Map.of("resultRevision",revision,"results",projection.project(executions.publicResults(id,ids,false)));
    }
    public SseEmitter stream(UUID id,long after,Page first) {
        var emitter=new SseEmitter(1_800_000L);
        var open=new AtomicBoolean(true);var task=new AtomicReference<Future<?>>();
        Runnable close=()->{open.set(false);var running=task.get();if(running!=null)running.cancel(true);};
        emitter.onCompletion(close);emitter.onTimeout(close);emitter.onError(error->close.run());
        task.set(subscriptions.submit(()->{
            long cursor=after;long lastHeartbeat=System.nanoTime();Page next=first;
            try {
                while(open.get()) {
                    for(var event:next.events()) {
                        if(!open.get())return;
                        cursor=((Number)event.get("seq")).longValue();
                        emitter.send(SseEmitter.event().id(Long.toString(cursor)).data(event));
                    }
                    if(next.terminal() && cursor>=next.lastEventSeq()) {emitter.complete();return;}
                    if(!next.hasMore())Thread.sleep(250);
                    if(System.nanoTime()-lastHeartbeat>TimeUnit.SECONDS.toNanos(15)) {
                        emitter.send(SseEmitter.event().comment("keepalive"));lastHeartbeat=System.nanoTime();
                    }
                    next=page(id,cursor);
                }
            } catch(InterruptedException ignored) {Thread.currentThread().interrupt();}
              catch(IOException | IllegalStateException ignored) {emitter.complete();}
              catch(RuntimeException failure) {emitter.complete();}
            finally {open.set(false);}
        }));
        if(!open.get())task.get().cancel(true);
        return emitter;
    }
    @PreDestroy void stop() {subscriptions.shutdownNow();}
}
