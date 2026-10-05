package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.*;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentRequestService {
    static final String INVALID="INVALID_AGENT_REQUEST";
    private static final Set<String> ACTIVE=Set.of("QUEUED","RUNNING","NEEDS_INPUT");
    private static final Set<String> INTENTS=Set.of("FORWARD_LOOKUP","REVERSE_SEARCH","RUN_COMPARISON","CHANGE_EXPLANATION","CONCEPT_EXPLANATION","CLARIFICATION","UNSUPPORTED");
    private final AgentRequestRepository requests;
    private final WorkspaceRepository workspace;
    private final SnapshotValidator validate;
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    public AgentRequestService(AgentRequestRepository requests,WorkspaceRepository workspace,SnapshotValidator validate,JdbcTemplate jdbc,ObjectMapper mapper){this.requests=requests;this.workspace=workspace;this.validate=validate;this.jdbc=jdbc;this.mapper=mapper;}
    public record Submission(String text,StateToken stateToken,RunRef selectedRunRef,RunRef baseline,List<RunRef> candidateReferences) {}
    public record Resume(long expectedRequestRevision,String pendingInputId,Map<String,Object> input) {}
    public record Claim(String workerId,int leaseSeconds) {}
    public record Mutation(long claimGeneration,long requestRevision,Integer leaseSeconds,String stage,String operationKind,Boolean dependsOnContext,
        Map<String,Object> payload,Map<String,Object> pendingInput,Map<String,Object> error,Map<String,Object> partialResult,List<RunRef> usedRunRefs,AgentResponse answer,Integer limit,List<RunRef> requiredRunRefs,
        Map<String,Object> reverseQuery,Boolean referencesOnly) {}
    private void require(boolean condition,String message){validate.require(condition,INVALID,message);}
    private void conflict(String code,String message){throw new IntakeException(code,409,message);}
    @Transactional public Map<String,Object> submit(Submission body,String key){
        var current=workspace.lock();WorkspaceService.epochs(body.stateToken(),current.stateToken());validate.key(key,INVALID);
        String replay=workspace.replay(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),"AGENT",key,body);
        if(replay!=null)return requests.view(requests.get(UUID.fromString(replay),false));
        WorkspaceService.revision(body.stateToken(),current.stateToken());validate.text(body.text(),INVALID,"text");require(body.text().length()<=16000,"text is too long");
        if(requests.latest(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),false)!=null)conflict("REQUEST_IN_PROGRESS","현재 요청을 완료하거나 취소한 뒤 질문해 주세요.");
        if(body.baseline()!=null)validate.ref(body.baseline(),INVALID);if(body.selectedRunRef()!=null){validate.ref(body.selectedRunRef(),INVALID);require(visible(body.selectedRunRef(),current),"selectedRunRef is not present in this workspace");}
        if(body.candidateReferences()!=null)validate.refs(body.candidateReferences(),INVALID,false);
        Map<String,Object> context=new LinkedHashMap<>();context.put("stateToken",current.stateToken());context.put("activeRun",body.baseline()==null?current.conversation().activeRun():body.baseline());
        context.put("candidateReference",current.candidateReference());context.put("candidateReferences",body.candidateReferences()==null?(current.candidateReference()==null?List.of():current.candidateReference().runs()):body.candidateReferences());
        context.put("selectedRunRef",body.selectedRunRef());
        var turns=current.conversation().turns();context.put("lastAnswer",turns.isEmpty()?null:turns.getLast().answerSnapshot());
        context.put("comparisonContext",turns.reversed().stream().filter(t->"compare_runs".equals(t.answerSnapshot().get("kind"))||"explain_change".equals(t.answerSnapshot().get("kind"))).map(TurnSnapshot::answerSnapshot).findFirst().orElse(null));
        UUID id=UUID.randomUUID();jdbc.update("insert into agent_request(id,workspace_epoch,conversation_epoch,status,question,submission,context_snapshot) values (?,?,?,'QUEUED',?,?::jsonb,?::jsonb)",id,current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),body.text(),requests.json(body),requests.json(context));
        workspace.remember(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),"AGENT",key,body,id.toString());workspace.advance();return requests.view(requests.get(id,false));
    }
    private boolean visible(RunRef ref,WorkspaceView current){return Objects.equals(ref,current.conversation().activeRun())||(current.candidateReference()!=null&&current.candidateReference().runs().contains(ref))||current.conversation().turns().stream().anyMatch(t->t.answerRunRefs().contains(ref));}
    @Transactional(readOnly=true) public Map<String,Object> status(UUID id){return requests.view(requests.get(id,false));}
    @Transactional public Map<String,Object> cancel(UUID id){var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);if(ACTIVE.contains(row.status()))requests.cancel(id,"CANCELLED_BY_USER");return requests.view(requests.get(id,false));}
    @Transactional public Map<String,Object> resume(UUID id,Resume body,String key){
        var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);validate.key(key,INVALID);require(body.input()!=null&&!body.input().isEmpty(),"input is required");require(requests.json(body.input()).length()<=20000,"input is too large");
        var previous=jdbc.queryForList("select request_revision,pending_input_id,input=?::jsonb as same from agent_input_event where request_id=? and idempotency_key=?",requests.json(body.input()),id,key);
        if(!previous.isEmpty()){var old=previous.getFirst();if(!Boolean.TRUE.equals(old.get("same"))||!Objects.equals(old.get("pending_input_id"),body.pendingInputId())||((Number)old.get("request_revision")).longValue()!=body.expectedRequestRevision()+1)conflict("IDEMPOTENCY_CONFLICT","Input key already used for a different response");return requests.view(row);}
        if(!"NEEDS_INPUT".equals(row.status())||row.revision()!=body.expectedRequestRevision()||row.pending()==null||!Objects.equals(row.pending().get("id"),body.pendingInputId()))conflict("STALE_REQUEST","The pending input changed");
        if(row.revision()>=10)conflict("INPUT_LIMIT","추가 질문 횟수 제한에 도달했습니다. 새 질문으로 시작해 주세요.");
        jdbc.update("insert into agent_input_event(id,request_id,request_revision,idempotency_key,pending_input_id,input) values (?,?,?,?,?,?::jsonb)",UUID.randomUUID(),id,row.revision()+1,key,body.pendingInputId(),requests.json(body.input()));
        jdbc.update("update agent_request set status='QUEUED',stage='resume',request_revision=request_revision+1,claim_generation=claim_generation+1,pending_input=null,lease_until=null,updated_at=now() where id=?",id);
        return requests.view(requests.get(id,false));
    }
    @Transactional public Map<String,Object> claim(Claim body){
        validate.text(body.workerId(),INVALID,"workerId");require(body.workerId().length()<=200,"workerId is too long");int seconds=lease(body.leaseSeconds());
        while(true){
            var ids=jdbc.queryForList("select id from agent_request where status='QUEUED' or (status='RUNNING' and lease_until<clock_timestamp()) order by created_at for update skip locked limit 1",UUID.class);
            Map<String,Object> result=new LinkedHashMap<>();if(ids.isEmpty()){result.put("request",null);return result;}UUID id=ids.getFirst();
            var previous=requests.get(id,false);Map<String,Object> counts=new LinkedHashMap<>(previous.attempts());String key="claim:"+previous.revision();int count=((Number)counts.getOrDefault(key,0)).intValue();
            if(count>=3){
                jdbc.update("update agent_request set status='FAILED',stage='failed',claim_generation=claim_generation+1,lease_until=null,pending_input=null,context_snapshot=null,partial_result=null,error=?::jsonb,updated_at=now() where id=?",requests.json(Map.of("code","CLAIM_ATTEMPT_LIMIT","message","작업 복구가 반복해서 실패했습니다. 새 질문으로 다시 시도해 주세요.")),id);
                requests.purgeTransient(id);continue;
            }
            counts.put(key,count+1);
            jdbc.update("update agent_request set status='RUNNING',worker_id=?,claim_generation=claim_generation+1,lease_until=clock_timestamp()+(? * interval '1 second'),attempts=?::jsonb,updated_at=now() where id=?",body.workerId(),seconds,requests.json(counts),id);
            var row=requests.get(id,false);var view=requests.view(row);result.put("request",view);result.put("claimGeneration",row.generation());result.put("requestRevision",row.revision());result.put("context",row.context());result.put("inputEvents",view.get("inputEvents"));return result;
        }
    }
    private int lease(Integer seconds){int value=seconds==null||seconds==0?60:seconds;require(value>=5&&value<=300,"leaseSeconds must be 5..300");return value;}
    private AgentRequestRepository.Row fence(UUID id,long generation,long revision){var row=requests.get(id,true);boolean alive=Boolean.TRUE.equals(jdbc.queryForObject("select lease_until>clock_timestamp() from agent_request where id=?",Boolean.class,id));if(!"RUNNING".equals(row.status())||row.generation()!=generation||row.revision()!=revision||!alive)conflict("STALE_CLAIM","Worker lease, generation or request revision is no longer valid");return row;}
    private void epochs(AgentRequestRepository.Row row,WorkspaceView current){if(row.workspaceEpoch()!=current.stateToken().workspaceEpoch()||row.conversationEpoch()!=current.stateToken().conversationEpoch())conflict("STALE_CONTEXT","Workspace or conversation changed");}
    @Transactional public Map<String,Object> heartbeat(UUID id,Mutation body){
        var current=workspace.lock();var row=fence(id,body.claimGeneration(),body.requestRevision());epochs(row,current);if(body.stage()!=null)require(body.stage().length()<=80,"stage is too long");
        if(body.operationKind()!=null)require(Set.of("forward_lookup","reverse_search","compare_runs","explain_change","explain_concept","unsupported").contains(body.operationKind()),"Unknown operationKind");
        if(body.operationKind()!=null&&row.context()!=null&&row.context().get("invalidationReason") instanceof String reason){
            boolean depends=body.dependsOnContext()==null?row.dependsOnContext():body.dependsOnContext();
            if(depends){requests.cancel(id,reason);return requests.view(requests.get(id,false));}
            Map<String,Object> context=new LinkedHashMap<>(row.context());context.remove("invalidationReason");jdbc.update("update agent_request set context_snapshot=?::jsonb where id=?",requests.json(context),id);
        }
        jdbc.update("update agent_request set lease_until=clock_timestamp()+(? * interval '1 second'),stage=coalesce(?,stage),operation_kind=coalesce(?,operation_kind),depends_on_context=coalesce(?,depends_on_context),updated_at=now() where id=?",lease(body.leaseSeconds()),body.stage(),body.operationKind(),body.dependsOnContext(),id);return requests.view(requests.get(id,false));
    }
    @Transactional public Map<String,Object> checkpoint(UUID id,long generation,long revision){fence(id,generation,revision);var values=jdbc.queryForList("select payload::text from agent_checkpoint where request_id=?",String.class,id);Map<String,Object> result=new LinkedHashMap<>();result.put("payload",values.isEmpty()?null:requests.read(values.getFirst()));return result;}
    @Transactional public Map<String,Object> saveCheckpoint(UUID id,Mutation body){fence(id,body.claimGeneration(),body.requestRevision());require(body.payload()!=null,"checkpoint payload is required");String payload=requests.json(body.payload());require(payload.length()<=16_000_000,"checkpoint payload is too large");jdbc.update("insert into agent_checkpoint(request_id,payload) values (?,?::jsonb) on conflict(request_id) do update set payload=excluded.payload,updated_at=now()",id,payload);return Map.of("saved",true);}
    @Transactional public Map<String,Object> attempt(UUID id,Mutation body){var row=fence(id,body.claimGeneration(),body.requestRevision());validate.text(body.stage(),INVALID,"stage");require(Set.of("interpret","explain","interpret_repair","explain_repair").contains(body.stage()),"Unknown model stage");int limit=body.limit()==null?4:body.limit();require(limit>=1&&limit<=4,"attempt limit must be 1..4");Map<String,Object> counts=new LinkedHashMap<>(row.attempts());String key=(body.stage().startsWith("interpret")?"interpret":"explain")+":"+row.revision();int count=((Number)counts.getOrDefault(key,0)).intValue();if(count>=limit)conflict("MODEL_ATTEMPT_LIMIT","Model attempt limit exhausted");counts.put(key,count+1);jdbc.update("update agent_request set attempts=?::jsonb,stage=?,updated_at=now() where id=?",requests.json(counts),body.stage(),id);return Map.of("attempt",count+1,"limit",limit);}
    @Transactional public Map<String,Object> context(UUID id,long generation,long revision){return context(id,generation,revision,List.of());}
    @Transactional public Map<String,Object> context(UUID id,long generation,long revision,List<RunRef> required){
        return context(id,generation,revision,required,null,false);
    }
    @Transactional public Map<String,Object> context(UUID id,long generation,long revision,List<RunRef> required,Map<String,Object> reverseQuery,Boolean referencesOnly){
        var current=workspace.lock();var row=fence(id,generation,revision);epochs(row,current);if(required==null)required=List.of();validate.refs(required,INVALID,false);
        boolean only=Boolean.TRUE.equals(referencesOnly);require(!only||reverseQuery==null,"referencesOnly and reverseQuery are mutually exclusive");
        ReverseContextQuery query=reverseQuery==null?null:new ReverseContextQuery(reverseQuery);
        Map<String,Object> manifest=row.manifest()==null?new LinkedHashMap<>():new LinkedHashMap<>(row.manifest());
        if(manifest.get("reverseQuery")!=null&&query!=null&&!mapper.valueToTree(manifest.get("reverseQuery")).equals(mapper.valueToTree(query.normalized())))conflict("MANIFEST_QUERY_CONFLICT","A materialized reverse query cannot change");
        boolean changed=row.manifest()==null;
        if(row.manifest()==null){
            // Pin identities before any context-derived numerical condition is calculated.
            var inventory=jdbc.query("select r.run_id,r.current_version_id::text from run r where r.current_version_id is not null order by r.run_id",(rs,n)->Map.of("runId",rs.getString(1),"runVersionId",rs.getString(2)));
            manifest.put("catalogRunRefs",inventory);manifest.put("runs",List.of());manifest.put("referencedRuns",List.of());manifest.put("context",row.context());manifest.put("createdAt",Instant.now().toString());
        }else if(!manifest.containsKey("catalogRunRefs")){
            List<Map<String,Object>> inventory=new ArrayList<>();for(Object value:(List<?>)manifest.get("runs")){Map<?,?> run=(Map<?,?>)value;inventory.add(Map.of("runId",run.get("runId"),"runVersionId",run.get("runVersionId")));}
            manifest.put("catalogRunRefs",inventory);changed=true;
        }
        Set<String> refs=new LinkedHashSet<>();
        // Stored answers can outlive deleted Runs. They are interpretation context,
        // not mandatory dependencies of an unrelated new lookup.
        if(row.context()!=null)for(String key:List.of("activeRun","selectedRunRef","candidateReferences","comparisonContext"))collectVersions(row.context().get(key),refs);
        required.forEach(ref->refs.add(ref.runVersionId()));
        Set<String> fetched=new HashSet<>();collectVersions(manifest.get("referencedRuns"),fetched);refs.removeAll(fetched);
        if(!refs.isEmpty()){
            List<Object> historical=new ArrayList<>((List<?>)manifest.get("referencedRuns"));historical.addAll(scalarVersions(refs.toArray(String[]::new)));
            manifest.put("referencedRuns",historical);changed=true;
        }
        Set<String> pinned=new LinkedHashSet<>();collectVersions(manifest.get("catalogRunRefs"),pinned);
        if(query!=null&&manifest.get("reverseQuery")==null){
            var sql=query.select(pinned.toArray(String[]::new));
            manifest.put("runs",jdbc.query(sql.text(),(rs,n)->scalarRow(rs.getString(1),rs.getObject(2)),sql.arguments().toArray()));
            manifest.put("reverseQuery",query.normalized());manifest.put("catalogMaterialized",true);changed=true;
        }else if(!only&&query==null&&!Boolean.TRUE.equals(manifest.get("catalogMaterialized"))){
            manifest.put("runs",scalarVersions(pinned.toArray(String[]::new)));manifest.put("catalogMaterialized",true);changed=true;
        }
        if(changed)jdbc.update("update agent_request set manifest=?::jsonb,updated_at=now() where id=?",requests.json(manifest),id);
        return manifest;
    }
    private List<Map<String,Object>> scalarVersions(String[] versions){return jdbc.query("select summary::text,jsonb_array_length(full_run->'sourceFiles') from run_version where id=any(?::uuid[]) order by run_id,registration_sequence",(rs,n)->scalarRow(rs.getString(1),rs.getObject(2)),(Object)versions);}
    private Map<String,Object> scalarRow(String json,Object sourceFileCount){var item=scalarSummary(json);item.put("sourceFileCount",sourceFileCount);return item;}
    private void collectVersions(Object value,Set<String> refs){if(value instanceof Map<?,?> map){if(map.get("runVersionId") instanceof String id)refs.add(id);for(var v:map.values())collectVersions(v,refs);}else if(value instanceof List<?> list)list.forEach(v->collectVersions(v,refs));}
    private Map<String,Object> scalarSummary(String json){
        Map<String,Object> source=requests.read(json),result=new LinkedHashMap<>();
        for(String key:List.of("runId","runVersionId","pressure","sourcePower","biasPower","metrics","units","convergenceStatus","qualityStatus","catalogStatus","registeredAt","presentationScore","note"))if(source.containsKey(key))result.put(key,source.get(key));
        if(source.get("analysis") instanceof Map<?,?> analysis){Map<String,Object> scalars=new LinkedHashMap<>();for(String key:List.of("hasDistribution","strictConvergence","finalResidualMax","electronTemperature","ionTemperature","gasTemperature","absorbedPower","alpha","plasmaResistance","plasmaReactance","dcOffset","peakToPeak","currentDensityPeak","electronDensity","ionDensity","metastableDensity","neutralDensity","ionFluxRaw","metastableFluxRaw","neutralFluxRaw"))if(analysis.containsKey(key))scalars.put(key,analysis.get(key));result.put("analysis",scalars);}
        return result;
    }
    @Transactional public Map<String,Object> needsInput(UUID id,Mutation body){fence(id,body.claimGeneration(),body.requestRevision());require(body.pendingInput()!=null,"pendingInput is required");validate.text((String)body.pendingInput().get("id"),INVALID,"pendingInput.id");validate.text((String)body.pendingInput().get("message"),INVALID,"pendingInput.message");require(requests.json(body.pendingInput()).length()<=20000,"pendingInput is too large");jdbc.update("update agent_request set status='NEEDS_INPUT',stage='wait_input',pending_input=?::jsonb,lease_until=null,updated_at=now() where id=?",requests.json(body.pendingInput()),id);return requests.view(requests.get(id,false));}
    @Transactional public Map<String,Object> fail(UUID id,Mutation body){
        var current=workspace.lock();var row=fence(id,body.claimGeneration(),body.requestRevision());epochs(row,current);require(body.error()!=null,"error is required");String code=(String)body.error().get("code"),message=(String)body.error().get("message");validate.text(code,INVALID,"error.code");validate.text(message,INVALID,"error.message");require(code.matches("[A-Z_]{1,80}")&&message.length()<=1000,"Invalid public error");
        if(body.partialResult()!=null){require("explain_change".equals(row.operationKind()),"Only a failed change explanation may retain comparison");validatePartialComparison(body.partialResult(),body.usedRunRefs());}
        jdbc.update("update agent_request set status='FAILED',stage='failed',error=?::jsonb,partial_result=?::jsonb,context_snapshot=null,lease_until=null,pending_input=null,updated_at=now() where id=?",requests.json(Map.of("code",code,"message",message)),requests.json(body.partialResult()),id);requests.purgeTransient(id);return requests.view(requests.get(id,false));
    }
    @Transactional public Map<String,Object> finalizeRequest(UUID id,Mutation body){
        var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);require(body.answer()!=null,"answer is required");
        if("COMPLETED".equals(row.status())){if(!mapper.readTree(requests.json(row.answer())).equals(mapper.valueToTree(body.answer())))conflict("IDEMPOTENCY_CONFLICT","Completed answer cannot change");return requests.view(row);}
        row=fence(id,body.claimGeneration(),body.requestRevision());var answer=body.answer();require(INTENTS.contains(answer.intent()==null?"":answer.intent()),"Invalid answer intent");require(answer.answerSnapshot()!=null,"Answer snapshot is required");require("v1".equals(answer.answerSnapshot().get("implementationId")),"Answer must identify v1");validate.refs(answer.usedRunRefs(),INVALID,false);validate.compact(answer.answerSnapshot(),INVALID,new HashSet<>(answer.usedRunRefs()));
        RunRef active=row.context()==null?null:mapper.convertValue(row.context().get("activeRun"),RunRef.class);if(active!=null&&!answer.usedRunRefs().contains(active))active=null;
        var turn=new TurnSnapshot(id.toString(),row.createdAt().toString(),row.question(),answer.intent(),active,answer.usedRunRefs(),answer.answerSnapshot(),new TurnUiSnapshot(false,List.of(),Map.of(),"common",null,false,null));
        workspace.append(turn);workspace.advance();jdbc.update("update agent_request set status='COMPLETED',stage='completed',final_answer=?::jsonb,turn_id=?,context_snapshot=null,lease_until=null,pending_input=null,updated_at=now() where id=?",requests.json(answer),id,id);requests.purgeTransient(id);return requests.view(requests.get(id,false));
    }
    private void validatePartialComparison(Map<String,Object> partial,List<RunRef> refs){
        validate.refs(refs,INVALID,false);require(refs.size()==2,"A partial comparison requires both Run versions");validate.compact(partial,INVALID,new HashSet<>(refs));
        Set<String> fields=Set.of("kind","resultStatus","baseline","target","conditions","changedConditions","metrics","quality","usedRunRefs","numericPolicyVersion","explanationComplete");
        require(partial.keySet().equals(fields),"Partial result must contain only the complete comparison contract");
        require("compare_runs".equals(partial.get("kind"))&&Boolean.FALSE.equals(partial.get("explanationComplete")),"Partial result must be a comparison with explanationComplete=false");
        require("v1".equals(partial.get("numericPolicyVersion")),"Unknown numeric policy");
        require(Set.of("COMPARISON_READY","COMPARISON_PARTIAL","NO_COMPARABLE_DATA").contains(String.valueOf(partial.get("resultStatus"))),"Invalid comparison status");
        require(mapper.valueToTree(refs.getFirst()).equals(mapper.valueToTree(partial.get("baseline")))&&mapper.valueToTree(refs.getLast()).equals(mapper.valueToTree(partial.get("target"))),"Comparison role references do not match inventory order");
        require(mapper.valueToTree(refs).equals(mapper.valueToTree(partial.get("usedRunRefs"))),"Comparison inventory mismatch");
        require(partial.get("conditions") instanceof List<?> conditions&&conditions.size()==3,"Comparison requires three condition rows");
        require(partial.get("metrics") instanceof List<?> metrics&&!metrics.isEmpty()&&metrics.size()<=3,"Comparison requires metric rows");
        validateComparisonRows((List<?>)partial.get("conditions"),true);validateComparisonRows((List<?>)partial.get("metrics"),false);
        require(partial.get("changedConditions") instanceof List<?> changed&&changed.stream().allMatch(v->Set.of("pressure","sourcePower","biasPower").contains(String.valueOf(v))),"Invalid changedConditions");
        require(partial.get("quality") instanceof Map<?,?> quality&&quality.keySet().equals(Set.of("baseline","target")),"Comparison quality metadata is required");
    }
    private void validateComparisonRows(List<?> values,boolean conditions){
        Set<String> fields=Set.of(conditions?"field":"metric","baseline","target","delta","unit","status","reason","percentChange","sourceValues");Set<String> seen=new HashSet<>();
        for(Object value:values){require(value instanceof Map<?,?>,"Comparison row must be an object");Map<?,?> row=(Map<?,?>)value;String metric=String.valueOf(row.get(conditions?"field":"metric"));
            require(fields.containsAll(row.keySet())&&row.keySet().containsAll(Set.of(conditions?"field":"metric","baseline","target","delta","unit","status","reason")),"Invalid comparison row fields");
            require((conditions?Set.of("pressure","sourcePower","biasPower"):Set.of("meanIonEnergy","ionFlux","iedWidth")).contains(metric)&&seen.add(metric),"Invalid or duplicate comparison metric");
            for(String key:List.of("baseline","target","delta","percentChange")){Object number=row.get(key);require(number==null||(number instanceof Number n&&Double.isFinite(n.doubleValue())),"Comparison values must be finite or null");}
            require(Set.of("AVAILABLE","UNAVAILABLE","PERCENT_UNAVAILABLE").contains(String.valueOf(row.get("status"))),"Invalid metric status");
        }
    }
}
