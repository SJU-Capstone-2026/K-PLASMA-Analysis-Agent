package com.kplasma.analysisagent.workspace;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.run.RunQueryService;
import java.time.Instant;
import java.util.*;
import org.springframework.stereotype.Component;

/** Compact scientific scalar snapshots are allowed; original graph arrays and full Runs are not. */
@Component
public class SnapshotValidator {
    private static final Set<String> GRAPH_KEYS=Set.of("graphs","graph","series","points","sourceRun","iedDistribution","residualTrace","iad","iead","current","potential","density","sourceFiles","fullRun","full_run","sourceShape","phaseRange","angleRange");
    private final RunQueryService runs;
    public SnapshotValidator(RunQueryService runs) {this.runs=runs;}
    public void require(boolean condition,String code,String message) {if(!condition)throw new IntakeException(code,400,message);}
    public void text(String text,String code,String field) {require(text!=null&&!text.isBlank(),code,field+" is required");}
    public void instant(String value,String code,String field) {try{Instant.parse(value);}catch(Exception e){throw new IntakeException(code,400,field+" must be an ISO instant");}}
    public void key(String key,String code) {text(key,code,"Idempotency-Key");require(key.length()<=200,code,"Idempotency-Key is too long");}
    public void ref(RunRef ref,String code) {
        require(ref!=null,code,"RunRef is required");text(ref.runId(),code,"runId");
        try {
            var full=runs.getVersion(UUID.fromString(ref.runVersionId()));
            require(full.runId().equals(ref.runId()),code,"RunRef id does not match its immutable version");
        } catch(IllegalArgumentException | NullPointerException e) {throw new IntakeException(code,400,"Invalid Run version id");}
        catch(IntakeException e) {if(e.status()==404)throw new IntakeException(code,400,"Run version does not exist");throw e;}
    }
    public void refs(List<RunRef> refs,String code,boolean uniqueDisplayIds) {
        require(refs!=null,code,"RunRefs are required");Set<RunRef> unique=new HashSet<>();Set<String> ids=new HashSet<>();
        for(var ref:refs){ref(ref,code);require(unique.add(ref),code,"Duplicate RunRef");if(uniqueDisplayIds)require(ids.add(ref.runId()),code,"Duplicate Run id");}
    }
    public void roleRefs(Object value,String code,Set<RunRef> inventory) {
        require(value instanceof List<?>,code,"Snapshot role references must be an array");
        List<RunRef> role=new ArrayList<>();
        for(Object item:(List<?>)value) {
            require(item instanceof Map<?,?>,code,"Snapshot role reference must be a compact RunRef");
            Map<?,?> map=(Map<?,?>)item;
            require(map.keySet().equals(Set.of("runId","runVersionId"))&&map.get("runId") instanceof String&&map.get("runVersionId") instanceof String,code,"Snapshot role reference requires exactly both string identities");
            RunRef ref=new RunRef((String)map.get("runId"),(String)map.get("runVersionId"));
            require(inventory.contains(ref),code,"Snapshot role reference is absent from answerRunRefs");role.add(ref);
        }
        refs(role,code,true);
    }
    public void compact(Object value,String code,Set<RunRef> inventory) {
        if(value instanceof Map<?,?> map) {
            for(var entry:map.entrySet()) {require(!GRAPH_KEYS.contains(entry.getKey()),code,"Graph or full Run payloads cannot be persisted in snapshots");compact(entry.getValue(),code,inventory);}
            if(map.containsKey("runVersionId")) {
                require(map.get("runId") instanceof String&&map.get("runVersionId") instanceof String,code,"Snapshot RunRef requires both string identities");
                var ref=new RunRef((String)map.get("runId"),(String)map.get("runVersionId"));ref(ref,code);
                if(inventory!=null)require(inventory.contains(ref),code,"Snapshot role RunRef is absent from the immutable inventory");
            }
        } else if(value instanceof List<?> list)for(var item:list)compact(item,code,inventory);
    }
}
