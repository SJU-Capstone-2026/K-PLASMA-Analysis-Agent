package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.AgentRequestService.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
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
    private final com.kplasma.analysisagent.run.RunOutputService outputs;
    public AgentWorkerController(AgentRequestService service,@Value("${kplasma.agent.worker-token:}") String token,com.kplasma.analysisagent.run.RunOutputService outputs){this.service=service;this.token=token;this.outputs=outputs;}
    public record OutputQuery(long claimGeneration,long requestRevision,java.util.List<com.kplasma.analysisagent.contract.RunDto.RunRef> runRefs,java.util.List<String> plotIds) {}
    @PostMapping("/requests/{id}/comparison-outputs") public com.kplasma.analysisagent.contract.RunOutputDto.Response outputs(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody OutputQuery body){
        authorize(token);var requestId=AgentRequestController.id(id);service.authorizeOutputs(requestId,body.claimGeneration(),body.requestRevision(),body.runRefs());
        var result=outputs.outputs(new com.kplasma.analysisagent.contract.RunOutputDto.Request(body.runRefs(),body.plotIds()),false);
        service.authorizeOutputs(requestId,body.claimGeneration(),body.requestRevision(),body.runRefs());return result;
    }
    private void authorize(String submitted){if(token.isBlank())throw new IntakeException("WORKER_NOT_CONFIGURED",503,"Agent worker authentication is not configured");if(submitted==null||!MessageDigest.isEqual(token.getBytes(StandardCharsets.UTF_8),submitted.getBytes(StandardCharsets.UTF_8)))throw new IntakeException("UNAUTHORIZED",401,"Worker authentication required");}
    @PostMapping("/claim") public Map<String,Object> claim(@RequestHeader(name="X-Agent-Token",required=false) String token,@RequestBody Claim body){authorize(token);return service.claim(body);}
    @PostMapping("/requests/{id}/events") public Map<String,Object> event(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody AgentPublicEvents.Write body){authorize(token);return service.publicEvent(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/heartbeat") public Map<String,Object> heartbeat(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.heartbeat(AgentRequestController.id(id),body);}
    @GetMapping("/requests/{id}/context") public Map<String,Object> context(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestParam long claimGeneration,@RequestParam long requestRevision){authorize(token);return service.context(AgentRequestController.id(id),claimGeneration,requestRevision);}
    @PostMapping("/requests/{id}/context") public Map<String,Object> context(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.context(AgentRequestController.id(id),body.claimGeneration(),body.requestRevision(),body.requiredRunRefs(),body.reverseQuery(),body.referencesOnly(),body.forwardQuery());}
    @GetMapping("/requests/{id}/checkpoint") public Map<String,Object> checkpoint(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestParam long claimGeneration,@RequestParam long requestRevision){authorize(token);return service.checkpoint(AgentRequestController.id(id),claimGeneration,requestRevision);}
    @PostMapping("/requests/{id}/checkpoint") public Map<String,Object> checkpoint(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.saveCheckpoint(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/plans")
    public Map<String,Object> v2Plan(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                    @PathVariable String id, @RequestBody V2Write body) {
        authorize(token); return service.acceptV2Plan(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/steps")
    public Map<String,Object> v2Step(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                    @PathVariable String id, @RequestBody V2Write body) {
        authorize(token); return service.reserveV2Step(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/context")
    public Map<String,Object> v2Context(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                       @PathVariable String id, @PathVariable String executionId, @RequestBody V2Write body) {
        authorize(token); return service.v2StepContext(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/decision-records")
    public Map<String,Object> v2DecisionRecords(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                               @PathVariable String id, @PathVariable String executionId, @RequestBody V2Write body) {
        authorize(token); return service.v2DecisionRecords(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/steps/{executionId}/comparison-outputs")
    public com.kplasma.analysisagent.contract.RunOutputDto.Response v2Outputs(
            @RequestHeader(name="X-Agent-Token",required=false) String token, @PathVariable String id,
            @PathVariable String executionId, @RequestBody OutputQuery body) {
        authorize(token);
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
        authorize(token); return service.saveV2Step(AgentRequestController.id(id), AgentRequestController.id(executionId), body);
    }

    @PostMapping("/requests/{id}/model-attempts")
    public Map<String,Object> v2Model(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                     @PathVariable String id, @RequestBody V2Write body) {
        authorize(token); return service.reserveV2Model(AgentRequestController.id(id), body);
    }

    @PostMapping("/requests/{id}/model-attempts/{attemptId}/complete")
    public Map<String,Object> v2Outcome(@RequestHeader(name="X-Agent-Token",required=false) String token,
                                       @PathVariable String id, @PathVariable String attemptId, @RequestBody V2Write body) {
        authorize(token); return service.completeV2Model(AgentRequestController.id(id), AgentRequestController.id(attemptId), body);
    }

    @PostMapping("/requests/{id}/attempt") public Map<String,Object> attempt(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.attempt(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/decision-records") public Map<String,Object> decisionRecords(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.decisionRecords(AgentRequestController.id(id),body.claimGeneration(),body.requestRevision());}
    @PostMapping("/requests/{id}/needs-input") public Map<String,Object> needsInput(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.needsInput(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/fail") public Map<String,Object> fail(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.fail(AgentRequestController.id(id),body);}
    @PostMapping("/requests/{id}/finalize") public Map<String,Object> finalizeRequest(@RequestHeader(name="X-Agent-Token",required=false) String token,@PathVariable String id,@RequestBody Mutation body){authorize(token);return service.finalizeRequest(AgentRequestController.id(id),body);}
}
