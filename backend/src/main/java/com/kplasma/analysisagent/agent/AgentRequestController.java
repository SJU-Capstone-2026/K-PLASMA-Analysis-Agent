package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.AgentRequestService.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent/requests")
public class AgentRequestController {
    private final AgentRequestService service;
    private final AgentEventReplayService replay;
    private final RunSelectionService selections;
    public AgentRequestController(AgentRequestService service,AgentEventReplayService replay,RunSelectionService selections){this.service=service;this.replay=replay;this.selections=selections;}
    static UUID id(String value){try{return UUID.fromString(value);}catch(Exception e){throw new IntakeException("INVALID_AGENT_REQUEST",400,"Invalid request id");}}
    @PostMapping public Map<String,Object> submit(@RequestBody Submission body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.submit(body,key);}
    @GetMapping("/{id}") public Map<String,Object> status(@PathVariable String id){return service.status(id(id));}
    private long cursor(long after,String lastEventId) {
        if(lastEventId==null || lastEventId.isBlank())return after;
        try{return Long.parseLong(lastEventId);}catch(NumberFormatException e){throw new IntakeException("INVALID_EVENT_CURSOR",400,"Invalid Last-Event-ID");}
    }
    @GetMapping(value="/{id}/events",params="format=json",produces="application/json")
    public AgentEventReplayService.Page eventPage(@PathVariable String id,@RequestParam(defaultValue="0") long after,
            @RequestHeader(name="Last-Event-ID",required=false) String lastEventId) {return replay.page(id(id),cursor(after,lastEventId));}
    @GetMapping(value="/{id}/events",params="!format",produces="text/event-stream")
    public org.springframework.http.ResponseEntity<org.springframework.web.servlet.mvc.method.annotation.SseEmitter> eventStream(
            @PathVariable String id,@RequestParam(defaultValue="0") long after,
            @RequestHeader(name="Last-Event-ID",required=false) String lastEventId) {
        long cursor=cursor(after,lastEventId);var request=id(id);var page=replay.page(request,cursor);
        if(page.terminal() && page.events().isEmpty())return org.springframework.http.ResponseEntity.noContent().build();
        return org.springframework.http.ResponseEntity.ok().contentType(org.springframework.http.MediaType.TEXT_EVENT_STREAM)
            .header("Cache-Control","no-cache").header("X-Accel-Buffering","no").body(replay.stream(request,cursor,page));
    }
    @GetMapping("/{id}/results") public Map<String,Object> results(@PathVariable String id,@RequestParam long resultRevision){return replay.results(id(id),resultRevision);}
    @GetMapping("/{id}/run-options") public Map<String,Object> runOptions(@PathVariable String id,@RequestParam String pendingInputId,@RequestParam(required=false) Integer format,@RequestParam(defaultValue="") String query,@RequestParam(defaultValue="ascending") String sort,@RequestParam(required=false) String cursor,@RequestParam(defaultValue="30") int pageSize){
        if(format==null)return service.runOptions(id(id),pendingInputId);
        if(format!=2)throw new IntakeException("CLIENT_REFRESH_REQUIRED",409,"실험 선택 화면이 업데이트되었습니다. 화면을 새로고침해 주세요.");
        return selections.page(id(id),pendingInputId,query,sort,cursor,pageSize);
    }
    @GetMapping("/{id}/run-options/count") public Map<String,Object> count(@PathVariable String id,@RequestParam String pendingInputId,@RequestParam(defaultValue="") String query){return selections.count(id(id),pendingInputId,query);}
    @GetMapping("/{id}/run-selection") public Map<String,Object> selected(@PathVariable String id,@RequestParam String pendingInputId,@RequestParam(required=false) String cursor,@RequestParam(defaultValue="30") int pageSize){return selections.selected(id(id),pendingInputId,cursor,pageSize);}
    @PostMapping("/{id}/run-selection") public Map<String,Object> change(@PathVariable String id,@RequestBody RunSelectionService.Change body,@RequestHeader(name="Idempotency-Key",required=false) String key){return selections.change(id(id),body,key);}
    @PostMapping("/{id}/resume") public Map<String,Object> resume(@PathVariable String id,@RequestBody Resume body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.resume(id(id),body,key);}
    @PostMapping("/{id}/cancel") public Map<String,Object> cancel(@PathVariable String id){return service.cancel(id(id));}
}
