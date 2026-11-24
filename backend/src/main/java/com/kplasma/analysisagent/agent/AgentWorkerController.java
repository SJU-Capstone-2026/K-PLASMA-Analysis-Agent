package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.AgentRequestService.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.agent.v2.GraphVersionPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/agent")
public class AgentWorkerController {
    private final AgentRequestService service;
    private final String token;
    private final String localToken;
    private final GraphVersionPolicy graphVersions;
    private final com.kplasma.analysisagent.run.RunOutputService outputs;
    public AgentWorkerController(AgentRequestService service,@Value("${kplasma.agent.worker-token:}") String token,
            com.kplasma.analysisagent.run.RunOutputService outputs,
            @Value("${kplasma.agent.local-worker-token:}") String localToken,GraphVersionPolicy graphVersions){
        this.service=service;this.token=token;this.outputs=outputs;this.localToken=localToken;this.graphVersions=graphVersions;
        if(graphVersions.allowsLocal()&&!graphVersions.localOnly()
                &&(token.isBlank()||localToken.isBlank()||same(token,localToken)))
            throw new IllegalArgumentException("SHARED_WORKER_KEYS_INVALID");
    }
    public record OutputQuery(long claimGeneration,long requestRevision,java.util.List<com.kplasma.analysisagent.contract.RunDto.RunRef> runRefs,java.util.List<String> plotIds) {}
    @PostMapping("/requests/{id}/comparison-outputs") public com.kplasma.analysisagent.contract.RunOutputDto.Response outputs(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody OutputQuery body){
        authorize(token,id);var requestId=AgentRequestController.id(id);service.authorizeOutputs(requestId,body.claimGeneration(),body.requestRevision(),body.runRefs());
        var result=outputs.outputs(new com.kplasma.analysisagent.contract.RunOutputDto.Request(body.runRefs(),body.plotIds()),false);
        service.authorizeOutputs(requestId,body.claimGeneration(),body.requestRevision(),body.runRefs());return result;
    }
    private static boolean same(String expected,String submitted){return submitted!=null&&MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8),submitted.getBytes(StandardCharsets.UTF_8));}
    private boolean authorize(String submitted){
        if(token.isBlank()&&(!graphVersions.allowsLocal()||localToken.isBlank()))
            throw new IntakeException("WORKER_NOT_CONFIGURED",503,"Agent worker authentication is not configured");
        if(!token.isBlank()&&same(token,submitted))return graphVersions.localOnly();
        if(graphVersions.allowsLocal()&&!localToken.isBlank()&&same(localToken,submitted))return true;
        throw new IntakeException("UNAUTHORIZED",401,"Worker authentication required");
    }
    private void authorize(String submitted,String id){
        boolean local=authorize(submitted);service.authorizeWorkerGraph(AgentRequestController.id(id),local);
    }
    @PostMapping("/claim") public Map<String,Object> claim(@RequestHeader(name="X-Agent-Token",required=false) String token,@RequestBody Claim body){
        boolean local=authorize(token);
        if(graphVersions.workerVersions(body.supportedGraphVersions()).stream().anyMatch(v -> "v2_localLLM".equals(v)!=local))
            throw new IntakeException("WORKER_GRAPH_FORBIDDEN",403,"Worker cannot access this graph");
        return service.claim(body);
    }
    @PostMapping("/requests/{id}/events") public Map<String,Object> event(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody AgentPublicEvents.Write body){authorize(token,id);return service.publicEvent(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/heartbeat") public Map<String,Object> heartbeat(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.heartbeat(AgentRequestController.id(id),body);}
    @GetMapping("/requests/{id}/context") public Map<String,Object> context(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestParam long claimGeneration,@RequestParam long requestRevision){authorize(token,id);return service.context(AgentRequestController.id(id),claimGeneration,requestRevision);}
    @PostMapping("/requests/{id}/context") public Map<String,Object> context(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.context(AgentRequestController.id(id),body.claimGeneration(),body.requestRevision(),body.requiredRunRefs(),body.reverseQuery(),body.referencesOnly(),body.forwardQuery());}
    @GetMapping("/requests/{id}/checkpoint") public Map<String,Object> checkpoint(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestParam long claimGeneration,@RequestParam long requestRevision){authorize(token,id);return service.checkpoint(AgentRequestController.id(id),claimGeneration,requestRevision);}
    @PostMapping("/requests/{id}/checkpoint") public Map<String,Object> checkpoint(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.saveCheckpoint(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/plans")
    public Map<String,Object> v2Plan(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                    @PathVariable String id, @RequestBody V2Write body) {
        authorize(token,id); return service.acceptV2Plan(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/steps")
    public Map<String,Object> v2Step(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                    @PathVariable String id, @RequestBody V2Write body) {
        authorize(token,id); return service.reserveV2Step(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/context")
    public Map<String,Object> v2Context(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                       @PathVariable String id, @PathVariable String executionId, @RequestBody V2Write body) {
        authorize(token,id); return service.v2StepContext(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/decision-records")
    public Map<String,Object> v2DecisionRecords(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                               @PathVariable String id, @PathVariable String executionId, @RequestBody V2Write body) {
        authorize(token,id); return service.v2DecisionRecords(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/comparison-outputs")
    public com.kplasma.analysisagent.contract.RunOutputDto.Response v2Outputs(
            @RequestHeader(name="X-Agent-Token",required=false) String token, @PathVariable String id,
            @PathVariable String executionId, @RequestBody OutputQuery body) {
        authorize(token,id);
        var requestId=AgentRequestController.id(id);
        var execution=AgentRequestController.id(executionId);
        var fence=new V2Write(body.claimGeneration(),body.requestRevision(),null,null,null,null,null);
        service.authorizeV2Outputs(requestId,execution,fence,body.runRefs());
        var result=outputs.outputs(new com.kplasma.analysisagent.contract.RunOutputDto.Request(body.runRefs(),body.plotIds()),false);
        service.authorizeV2Outputs(requestId,execution,fence,body.runRefs());
        return result;
    }

    @PostMapping("/requests/{id}/steps/{executionId}/result")
    public Map<String,Object> v2Result(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                      @PathVariable String id, @PathVariable String executionId, @RequestBody V2Write body) {
        authorize(token,id); return service.saveV2Step(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/model-attempts")
    public Map<String,Object> v2Model(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                     @PathVariable String id, @RequestBody V2Write body) {
        authorize(token,id); return service.reserveV2Model(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/model-attempts/{attemptId}/complete")
    public Map<String,Object> v2Outcome(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                       @PathVariable String id, @PathVariable String attemptId, @RequestBody V2Write body) {
        authorize(token,id); return service.completeV2Model(AgentRequestController.id(id), AgentRequestController.id(attemptId), body);
    }

    @PostMapping("/requests/{id}/attempt") public Map<String,Object> attempt(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.attempt(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/decision-records") public Map<String,Object> decisionRecords(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.decisionRecords(AgentRequestController.id(id),body.claimGeneration(),body.requestRevision());}
    @PostMapping("/requests/{id}/needs-input") public Map<String,Object> needsInput(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.needsInput(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/fail") public Map<String,Object> fail(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.fail(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/finalize") public Map<String,Object> finalizeRequest(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token,id);return service.finalizeRequest(AgentRequestController.id(id),body);}
}
