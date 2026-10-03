package com.kplasma.analysisagent.workspace;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.UUID;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
@RestController
@RequestMapping("/api/workspace")
public class WorkspaceController {
    private final WorkspaceService service;
    public WorkspaceController(WorkspaceService service){this.service=service;}
    @GetMapping public WorkspaceView get(){return service.load();}
    @PostMapping("/turns") public WorkspaceView append(@RequestBody TurnWrite body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.appendTurn(body.stateToken(),body.turn(),key);}
    @PatchMapping("/turns/{id}/ui") public WorkspaceView ui(@PathVariable String id,@RequestBody UiWrite body){UUID uuid;try{uuid=UUID.fromString(id);}catch(Exception e){throw new IntakeException("INVALID_WORKSPACE",400,"Invalid turn id");}return service.updateTurnUi(uuid,body.stateToken(),body.ui());}
    @PutMapping("/reference") public WorkspaceView reference(@RequestBody ReferenceWrite body){return service.setReference(body.stateToken(),body.candidateReference(),body.activeRun());}
    @PostMapping("/new-conversation") public WorkspaceView conversation(@RequestBody TokenWrite body){return service.newConversation(body.stateToken());}
    @PostMapping("/reset") public WorkspaceView reset(@RequestBody TokenWrite body){return service.reset(body.stateToken());}
    @ExceptionHandler(HttpMessageNotReadableException.class) public org.springframework.http.ResponseEntity<com.kplasma.analysisagent.contract.WorkspaceDto.Error> malformed(){return org.springframework.http.ResponseEntity.badRequest().body(new com.kplasma.analysisagent.contract.WorkspaceDto.Error("INVALID_WORKSPACE","Invalid workspace request",null,null,UUID.randomUUID().toString()));}
}
