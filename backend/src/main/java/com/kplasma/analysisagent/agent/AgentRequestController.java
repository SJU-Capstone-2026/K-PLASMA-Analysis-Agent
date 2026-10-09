package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.AgentRequestService.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent/requests")
public class AgentRequestController {
    private final AgentRequestService service;
    public AgentRequestController(AgentRequestService service){this.service=service;}
    static UUID id(String value){try{return UUID.fromString(value);}catch(Exception e){throw new IntakeException("INVALID_AGENT_REQUEST",400,"Invalid request id");}}
    @PostMapping public Map<String,Object> submit(@RequestBody Submission body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.submit(body,key);}
    @GetMapping("/{id}") public Map<String,Object> status(@PathVariable String id){return service.status(id(id));}
    @GetMapping("/{id}/run-options") public Map<String,Object> runOptions(@PathVariable String id,@RequestParam String pendingInputId){return service.runOptions(id(id),pendingInputId);}
    @PostMapping("/{id}/resume") public Map<String,Object> resume(@PathVariable String id,@RequestBody Resume body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.resume(id(id),body,key);}
    @PostMapping("/{id}/cancel") public Map<String,Object> cancel(@PathVariable String id){return service.cancel(id(id));}
}
