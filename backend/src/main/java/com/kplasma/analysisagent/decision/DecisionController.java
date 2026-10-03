package com.kplasma.analysisagent.decision;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
@RestController
@RequestMapping("/api/decisions")
public class DecisionController {
    private final DecisionService service;
    public DecisionController(DecisionService service){this.service=service;}
    @GetMapping public List<DecisionRecord> get(){return service.list();}
    @PostMapping public DecisionRecord save(@RequestBody DecisionWrite body,@RequestHeader(name="Idempotency-Key",required=false) String key){return service.save(body.workspaceEpoch(),body,key);}
    @ExceptionHandler(HttpMessageNotReadableException.class) public org.springframework.http.ResponseEntity<com.kplasma.analysisagent.contract.WorkspaceDto.Error> malformed(){return org.springframework.http.ResponseEntity.badRequest().body(new com.kplasma.analysisagent.contract.WorkspaceDto.Error("INVALID_DECISION","Invalid decision request",null,null,UUID.randomUUID().toString()));}
}
