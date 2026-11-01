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
    private static final Set<String> INTENTS=Set.of("FORWARD_LOOKUP","REVERSE_SEARCH","RUN_COMPARISON","GENERAL_ANSWER","CHANGE_EXPLANATION","CONCEPT_EXPLANATION","CLARIFICATION","UNSUPPORTED");
    private final AgentRequestRepository requests;
    private final WorkspaceRepository workspace;
    private final SnapshotValidator validate;
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final RunSelectionService selections;
    public AgentRequestService(AgentRequestRepository requests,WorkspaceRepository workspace,SnapshotValidator validate,JdbcTemplate jdbc,ObjectMapper mapper,RunSelectionService selections){this.requests=requests;this.workspace=workspace;this.validate=validate;this.jdbc=jdbc;this.mapper=mapper;this.selections=selections;}
    public record ReferenceOrigin(RunRef ref,String kind,String turnId,String groupId) {}
    public record Submission(String text,StateToken stateToken,RunRef selectedRunRef,RunRef baseline,List<RunRef> candidateReferences,List<RunRef> attachedRunRefs,List<ReferenceOrigin> referenceOrigins) {}
    public record Resume(long expectedRequestRevision,String pendingInputId,Map<String,Object> input) {}
    public record Claim(String workerId,int leaseSeconds) {}
    public record Mutation(long claimGeneration,long requestRevision,Integer leaseSeconds,String stage,String operationKind,Boolean dependsOnContext,
        Map<String,Object> payload,Map<String,Object> pendingInput,Map<String,Object> error,Map<String,Object> partialResult,List<RunRef> usedRunRefs,AgentResponse answer,Integer limit,List<RunRef> requiredRunRefs,
        Map<String,Object> reverseQuery,Boolean referencesOnly,Map<String,Object> forwardQuery) {}
    private void require(boolean condition,String message){validate.require(condition,INVALID,message);}
    private void conflict(String code,String message){throw new IntakeException(code,409,message);}
    @Transactional public Map<String,Object> submit(Submission body,String key){
        var current=workspace.lock();WorkspaceService.epochs(body.stateToken(),current.stateToken());validate.key(key,INVALID);
        String replay=workspace.replay(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),"AGENT",key,body);
        if(replay!=null)return requests.view(requests.get(UUID.fromString(replay),false));
        WorkspaceService.revision(body.stateToken(),current.stateToken());validate.text(body.text(),INVALID,"text");require(body.text().length()<=16000,"text is too long");
        if(requests.latest(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),false)!=null)conflict("REQUEST_IN_PROGRESS","현재 요청을 완료하거나 취소한 뒤 질문해 주세요.");
        var attached=body.attachedRunRefs()==null?List.<RunRef>of():body.attachedRunRefs();validate.bulkRefs(attached,INVALID);
        var explicit=explicitReferences(attached,body.referenceOrigins(),current,body.baseline());
        if(body.baseline()!=null&&!attached.contains(body.baseline()))validate.ref(body.baseline(),INVALID);if(body.selectedRunRef()!=null){if(!attached.contains(body.selectedRunRef()))validate.ref(body.selectedRunRef(),INVALID);require(visible(body.selectedRunRef(),current),"selectedRunRef is not present in this workspace");}
        if(body.candidateReferences()!=null)validate.bulkRefs(body.candidateReferences(),INVALID);
        Map<String,Object> context=new LinkedHashMap<>();context.put("stateToken",current.stateToken());context.put("activeRun",body.baseline()==null?current.conversation().activeRun():body.baseline());
        context.put("candidateReference",current.candidateReference());context.put("candidateReferences",body.candidateReferences()==null?(current.candidateReference()==null?List.of():current.candidateReference().runs()):body.candidateReferences());
        context.put("selectedRunRef",body.selectedRunRef());
        context.put("comparisonReference",explicit);context.put("recentContext",recentContext(current.conversation().turns()));
        var turns=current.conversation().turns();context.put("lastAnswer",turns.isEmpty()?null:turns.getLast().answerSnapshot());
        context.put("comparisonContext",turns.reversed().stream().filter(t->"compare_runs".equals(t.answerSnapshot().get("kind"))||"explain_change".equals(t.answerSnapshot().get("kind"))).map(TurnSnapshot::answerSnapshot).findFirst().orElse(null));
        UUID id=UUID.randomUUID();jdbc.update("insert into agent_request(id,workspace_epoch,conversation_epoch,status,question,submission,context_snapshot) values (?,?,?,'QUEUED',?,?::jsonb,?::jsonb)",id,current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),body.text(),requests.json(body),requests.json(context));
        workspace.remember(current.stateToken().workspaceEpoch(),current.stateToken().conversationEpoch(),"AGENT",key,body,id.toString());workspace.advance();return requests.view(requests.get(id,false));
    }
    private boolean visible(RunRef ref,WorkspaceView current){return Objects.equals(ref,current.conversation().activeRun())||(current.candidateReference()!=null&&current.candidateReference().runs().contains(ref))||current.conversation().turns().stream().anyMatch(t->t.answerRunRefs().contains(ref));}
    private Map<String,Object> explicitReferences(List<RunRef> refs,List<ReferenceOrigin> origins,WorkspaceView current,RunRef baseline){
        if(origins==null)origins=List.of();require(origins.size()==refs.size(),"Reference origins must match attached refs");
        List<Map<String,Object>> entries=new ArrayList<>();String baselineKey=null;
        for(int i=0;i<refs.size();i++){
            var ref=refs.get(i);var origin=origins.get(i);require(Objects.equals(origin.ref(),ref),"Reference origin order mismatch");
            require(Set.of("run_tag","candidate_group").contains(String.valueOf(origin.kind())),"Unknown reference origin");
            var turn=current.conversation().turns().stream().filter(t->t.id().equals(origin.turnId())).findFirst().orElse(null);
            require(turn!=null&&turn.answerRunRefs().contains(ref),"Reference must originate in an actual saved answer");
            require(!"candidate_group".equals(origin.kind())||groupContains(turn,origin.groupId(),ref),"Candidate group must contain the exact saved Run");
            String key="R"+(i+1);Map<String,Object> source=new LinkedHashMap<>();source.put("kind",origin.kind());source.put("turnId",origin.turnId());source.put("groupId",origin.groupId());source.put("pendingInputId",null);
            entries.add(Map.of("key",key,"ref",ref,"origin",source));if(Objects.equals(ref,baseline))baselineKey=key;
        }
        require(baseline==null||refs.isEmpty()||baselineKey!=null,"Baseline must be attached");
        Map<String,Object> result=new LinkedHashMap<>();result.put("entries",entries);result.put("baselineKey",baselineKey);return result;
    }
    private boolean groupContains(TurnSnapshot turn,String groupId,RunRef ref){
        if(groupId==null)return false;
        var snapshot=turn.answerSnapshot();
        if(snapshot.get("result") instanceof Map<?,?> result){
            Object candidates=null;
            if("common".equals(groupId))candidates="forward_lookup".equals(result.get("kind"))?result.get("candidates"):result.containsKey("commonRunRefs")?result.get("commonRunRefs"):result.get("commonCandidates");
            else if(groupId.startsWith("objective-")&&result.get("objectiveResults") instanceof List<?> groups){
                try{int index=Integer.parseInt(groupId.substring(10));if(index>=0&&index<groups.size()){var group=(Map<?,?>)groups.get(index);candidates=group.containsKey("candidateRefs")?group.get("candidateRefs"):group.get("candidates");}}catch(NumberFormatException ignored){return false;}
            }else if("near".equals(groupId))candidates=result.get("nearMisses");
            if(candidates instanceof List<?> rows)for(Object value:rows){var row=(Map<?,?>)value;var run=row.get("run") instanceof Map<?,?> nested?nested:row;if(Objects.equals(run.get("runId"),ref.runId())&&Objects.equals(run.get("runVersionId"),ref.runVersionId()))return true;}
            return false;
        }
        var legacy=snapshot.get("nestedAnswer") instanceof Map<?,?> nested?nested:snapshot;
        if(legacy.get("candidateGroups") instanceof Map<?,?> container&&container.get("groups") instanceof List<?> groups)
            for(Object value:groups){var group=(Map<?,?>)value;if(Objects.equals(groupId,group.get("id"))&&group.get("candidates") instanceof List<?> rows)
                for(Object candidate:rows)if(Objects.equals(ref.runId(),((Map<?,?>)candidate).get("runId")))return true;}
        return false;
    }
    private String displayedAnswer(Map<String,Object> snapshot){
        StringBuilder text=new StringBuilder(String.valueOf(snapshot.getOrDefault("summary","")));
        if(snapshot.get("result") instanceof Map<?,?> result&&result.get("markdown") instanceof String markdown)return markdown;
        if(snapshot.get("answer") instanceof Map<?,?> answer){
            Set<?> selected=answer.get("observationIds") instanceof List<?> ids?new HashSet<>(ids):Set.of();
            if(snapshot.get("result") instanceof Map<?,?> result&&result.get("observations") instanceof List<?> rows)
                for(Object value:rows){var observation=(Map<?,?>)value;if(selected.contains(observation.get("id")))text.append("\n").append(observation.get("text"));}
            if(answer.get("interpretations") instanceof List<?> rows)for(Object value:rows){var interpretation=(Map<?,?>)value;text.append("\n").append(interpretation.get("text"));if(interpretation.get("assumptions") instanceof List<?> assumptions)for(Object assumption:assumptions)text.append("\n").append(assumption);}
            if(answer.get("limitations") instanceof List<?> limitations)for(Object limitation:limitations)text.append("\n").append(limitation);
        }
        return text.toString();
    }
    private Map<String,Object> recentContext(List<TurnSnapshot> turns){
        List<Map<String,Object>> selected=new ArrayList<>();int chars=0;int omitted=turns.size();
        for(var turn:turns.reversed()){
            if(selected.size()>=6)break;String display=displayedAnswer(turn.answerSnapshot());
            int size=turn.question().length()+display.length();if(chars+size>16000)break;
            selected.addFirst(Map.of("turnId",turn.id(),"question",turn.question(),"answer",display));chars+=size;omitted--;
        }
        return Map.of("turns",selected,"omittedTurnCount",omitted,"maxTurns",6,"maxCharacters",16000);
    }
    private List<RunRef> entryRefs(Object snapshot){
        if(!(snapshot instanceof Map<?,?> map)||!(map.get("entries") instanceof List<?> entries))return List.of();
        return entries.stream().map(value->mapper.convertValue(((Map<?,?>)value).get("ref"),RunRef.class)).toList();
    }
    @Transactional(readOnly=true) public Map<String,Object> status(UUID id){return requests.view(requests.get(id,false));}
    @Transactional public Map<String,Object> cancel(UUID id){var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);if(ACTIVE.contains(row.status()))requests.cancel(id,"CANCELLED_BY_USER");return requests.view(requests.get(id,false));}
    @Transactional public Map<String,Object> resume(UUID id,Resume body,String key){
        var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);validate.key(key,INVALID);require(body.input()!=null&&!body.input().isEmpty(),"input is required");require(requests.json(body.input()).length()<=20000,"input is too large");
        var previous=jdbc.queryForList("select request_revision,pending_input_id,(input - 'comparisonReference')=?::jsonb as same from agent_input_event where request_id=? and idempotency_key=?",requests.json(body.input()),id,key);
        if(!previous.isEmpty()){var old=previous.getFirst();if(!Boolean.TRUE.equals(old.get("same"))||!Objects.equals(old.get("pending_input_id"),body.pendingInputId())||((Number)old.get("request_revision")).longValue()!=body.expectedRequestRevision()+1)conflict("IDEMPOTENCY_CONFLICT","Input key already used for a different response");return requests.view(row);}
        if(!"NEEDS_INPUT".equals(row.status())||row.revision()!=body.expectedRequestRevision()||row.pending()==null||!Objects.equals(row.pending().get("id"),body.pendingInputId()))conflict("STALE_REQUEST","The pending input changed");
        if(row.revision()>=10)conflict("INPUT_LIMIT","추가 질문 횟수 제한에 도달했습니다. 새 질문으로 시작해 주세요.");
        Map<String,Object> event=new LinkedHashMap<>(body.input());
        if("run_selection".equals(row.pending().get("type"))){
            require("run_selection".equals(body.input().get("type")),"Run selection input is required");
            var snapshot=selections.resolve(id,body.pendingInputId(),body.input(),Boolean.TRUE.equals(row.pending().get("baselineRequired")));
            validate.bulkRefs(entryRefs(snapshot),INVALID);
            Map<String,Object> context=new LinkedHashMap<>(row.context());context.put("comparisonReference",snapshot);context.remove("comparisonOptions");
            jdbc.update("update agent_request set context_snapshot=?::jsonb,manifest=null where id=?",requests.json(context),id);event.put("comparisonReference",snapshot);
            selections.finish(id);
        }else if("comparison_options".equals(row.pending().get("type"))){
            require("comparison_options".equals(body.input().get("type")),"Comparison options input is required");
            require(body.input().keySet().stream().allMatch(Set.of("type","baselineKey","trendAxis")::contains),"Unexpected comparison option");
            Object baseline=body.input().get("baselineKey"),axis=body.input().get("trendAxis");
            require(baseline==null||((List<?>)row.pending().get("allowedRunKeys")).contains(baseline),"Unknown baseline key");
            require(axis==null||((List<?>)row.pending().get("allowedTrendAxes")).contains(axis),"Unknown trend axis");
            for(Object field:(List<?>)row.pending().get("fields"))require(body.input().get(field)!=null,"Required comparison option missing");
        }
        jdbc.update("insert into agent_input_event(id,request_id,request_revision,idempotency_key,pending_input_id,input) values (?,?,?,?,?,?::jsonb)",UUID.randomUUID(),id,row.revision()+1,key,body.pendingInputId(),requests.json(event));
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
    @Transactional public void authorizeOutputs(UUID id,long generation,long revision,List<RunRef> refs){
        var row=fence(id,generation,revision);require("compare_runs".equals(row.operationKind()),"Only comparisons load outputs");
        require(refs!=null&&!refs.isEmpty()&&entryRefs(row.context().get("comparisonReference")).containsAll(refs),"Output query must use the fixed comparison selection");
    }
    private void epochs(AgentRequestRepository.Row row,WorkspaceView current){if(row.workspaceEpoch()!=current.stateToken().workspaceEpoch()||row.conversationEpoch()!=current.stateToken().conversationEpoch())conflict("STALE_CONTEXT","Workspace or conversation changed");}
    @Transactional public Map<String,Object> heartbeat(UUID id,Mutation body){
        var current=workspace.lock();var row=fence(id,body.claimGeneration(),body.requestRevision());epochs(row,current);if(body.stage()!=null)require(body.stage().length()<=80,"stage is too long");
        if(body.operationKind()!=null)require(Set.of("forward_lookup","reverse_search","compare_runs","generate_answer","explain_change","explain_concept","unsupported").contains(body.operationKind()),"Unknown operationKind");
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
        return context(id,generation,revision,required,reverseQuery,referencesOnly,null);
    }
    @Transactional public Map<String,Object> context(UUID id,long generation,long revision,List<RunRef> required,Map<String,Object> reverseQuery,Boolean referencesOnly,Map<String,Object> forwardQuery){
        var current=workspace.lock();var row=fence(id,generation,revision);epochs(row,current);if(required==null)required=List.of();
        require(!Boolean.TRUE.equals(referencesOnly)||reverseQuery==null,"referencesOnly and reverseQuery are mutually exclusive");
        require(forwardQuery==null||("forward_lookup".equals(row.operationKind())&&reverseQuery==null&&!Boolean.TRUE.equals(referencesOnly)),"forwardQuery is exclusive to a forward lookup");
        ForwardContextQuery forward=forwardQuery==null?null:new ForwardContextQuery(forwardQuery);
        if("forward_lookup".equals(row.operationKind())&&(forward!=null||Boolean.TRUE.equals(referencesOnly)||(row.manifest()!=null&&Boolean.TRUE.equals(row.manifest().get("forwardScoped"))))){
            require(reverseQuery==null,"A forward manifest cannot use reverseQuery");
            var scoped=forwardContext(id,row,required,forward);
            if(scoped!=null)return scoped;
        }
        if("compare_runs".equals(row.operationKind())&&row.context()!=null&&row.context().containsKey("comparisonReference"))return comparisonContext(id,row,required,reverseQuery,referencesOnly);
        if(reverseQuery!=null||Boolean.TRUE.equals(referencesOnly))return reverseContext(id,row,required,reverseQuery,referencesOnly);
        validate.refs(required,INVALID,false);
        Map<String,Object> manifest=row.manifest()==null?new LinkedHashMap<>():new LinkedHashMap<>(row.manifest());
        boolean changed=row.manifest()==null;
        if(row.manifest()==null||Boolean.TRUE.equals(manifest.remove("forwardScoped"))){
            changed=true;
            // Pin identities before any context-derived numerical condition is calculated.
            var inventory=jdbc.query("select r.run_id,r.current_version_id::text from run r where r.current_version_id is not null order by r.run_id",(rs,n)->Map.of("runId",rs.getString(1),"runVersionId",rs.getString(2)));
            manifest.put("catalogRunRefs",inventory);manifest.put("runs",List.of());manifest.put("referencedRuns",List.of());manifest.put("context",row.context());manifest.put("createdAt",Instant.now().toString());
        }else if(!manifest.containsKey("catalogRunRefs")){
            manifest.put("catalogRunRefs",jdbc.query("select r.run_id,r.current_version_id::text from run r where r.current_version_id is not null order by r.run_id",(rs,n)->Map.of("runId",rs.getString(1),"runVersionId",rs.getString(2))));changed=true;
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
        if(!Boolean.TRUE.equals(manifest.get("catalogMaterialized"))){
            manifest.put("runs",scalarVersions(pinned.toArray(String[]::new)));manifest.put("catalogMaterialized",true);changed=true;
        }
        if(changed)jdbc.update("update agent_request set manifest=?::jsonb,updated_at=now() where id=?",requests.json(manifest),id);
        return manifest;
    }
    private Map<String,Object> forwardContext(UUID id,AgentRequestRepository.Row row,List<RunRef> required,ForwardContextQuery query){
        // Already captured legacy inventories keep their original versions on resume.
        if(row.manifest()!=null&&!Boolean.TRUE.equals(row.manifest().get("forwardScoped")))return null;
        validate.refs(required,INVALID,false);
        Map<String,Object> manifest=row.manifest()==null?new LinkedHashMap<>():new LinkedHashMap<>(row.manifest());
        if(manifest.get("forwardQuery") instanceof Map<?,?> previous){
            if(query!=null&&!mapper.valueToTree(previous).equals(mapper.valueToTree(query.normalized())))conflict("MANIFEST_QUERY_CONFLICT","A materialized forward query cannot change");
            Set<String> fetched=new HashSet<>();collectVersions(manifest.get("referencedRuns"),fetched);
            var additional=required.stream().map(RunRef::runVersionId).filter(v->!fetched.contains(v)).toArray(String[]::new);
            if(additional.length>0){
                List<Object> historical=new ArrayList<>((List<?>)manifest.get("referencedRuns"));historical.addAll(scalarVersions(additional));
                manifest.put("referencedRuns",historical);
                jdbc.update("update agent_request set manifest=?::jsonb,updated_at=now() where id=?",requests.json(manifest),id);
            }
            return manifest;
        }
        if(query!=null){
            String runId=query.runId();
            var matches=runId==null?List.<Map<String,Object>>of():jdbc.query(
                "select v.summary::text,jsonb_array_length(v.full_run->'sourceFiles') from run r join run_version v on v.id=r.current_version_id where r.run_id=?",
                (rs,n)->scalarRow(rs.getString(1),rs.getObject(2)),runId);
            // Preserve the existing nearest/exclusion behavior when there is no usable exact match.
            if(matches.size()!=1||!query.matches(matches.getFirst()))return null;
            var match=matches.getFirst();
            manifest.put("runs",matches);
            manifest.put("catalogRunRefs",List.of(Map.of("runId",match.get("runId"),"runVersionId",match.get("runVersionId"))));
            manifest.put("forwardQuery",query.normalized());manifest.put("catalogMaterialized",true);
        }
        manifest.putIfAbsent("runs",List.of());manifest.putIfAbsent("catalogRunRefs",List.of());
        manifest.putIfAbsent("referencedRuns",List.of());manifest.putIfAbsent("context",row.context());
        manifest.putIfAbsent("createdAt",Instant.now().toString());manifest.put("forwardScoped",true);
        Set<String> refs=new LinkedHashSet<>();
        if(query==null&&row.context()!=null)for(String key:List.of("activeRun","selectedRunRef"))collectVersions(row.context().get(key),refs);
        required.forEach(ref->refs.add(ref.runVersionId()));
        Set<String> fetched=new HashSet<>();collectVersions(manifest.get("referencedRuns"),fetched);refs.removeAll(fetched);
        if(!refs.isEmpty()){
            List<Object> historical=new ArrayList<>((List<?>)manifest.get("referencedRuns"));historical.addAll(scalarVersions(refs.toArray(String[]::new)));
            manifest.put("referencedRuns",historical);
        }
        jdbc.update("update agent_request set manifest=?::jsonb,updated_at=now() where id=?",requests.json(manifest),id);
        return manifest;
    }
    private Map<String,Object> reverseContext(UUID id,AgentRequestRepository.Row row,List<RunRef> required,Map<String,Object> reverseQuery,Boolean referencesOnly){
        boolean only=Boolean.TRUE.equals(referencesOnly);
        require(!only||reverseQuery==null,"referencesOnly and reverseQuery are mutually exclusive");
        ReverseContextQuery query=reverseQuery==null?null:new ReverseContextQuery(reverseQuery);
        validate.bulkRefs(required,INVALID);
        Map<String,Object> manifest=row.manifest()==null?new LinkedHashMap<>():new LinkedHashMap<>(row.manifest());
        boolean changed=row.manifest()==null;
        if(changed){
            manifest.put("runs",List.of());manifest.put("referencedRuns",List.of());manifest.put("context",row.context());manifest.put("createdAt",Instant.now().toString());
        }
        if(manifest.get("reverseQuery")!=null&&query!=null&&!mapper.valueToTree(manifest.get("reverseQuery")).equals(mapper.valueToTree(query.normalized())))
            conflict("MANIFEST_QUERY_CONFLICT","A materialized reverse query cannot change");
        Set<String> refs=new LinkedHashSet<>();required.forEach(ref->refs.add(ref.runVersionId()));
        Set<String> fetched=new HashSet<>();collectVersions(manifest.get("referencedRuns"),fetched);refs.removeAll(fetched);
        if(!refs.isEmpty()){
            List<Object> selected=new ArrayList<>((List<?>)manifest.get("referencedRuns"));selected.addAll(scalarVersions(refs.toArray(String[]::new)));
            manifest.put("referencedRuns",selected);changed=true;
        }
        if(query!=null&&!Boolean.TRUE.equals(manifest.get("catalogMaterialized"))){
            var sql=query.select();
            var runs=jdbc.query(sql.text(),(rs,n)->scalarRow(rs.getString(1),rs.getObject(2)),sql.arguments().toArray());
            manifest.put("runs",runs);
            manifest.put("selectedRunRefs",runs.stream().map(run->Map.of("runId",run.get("runId"),"runVersionId",run.get("runVersionId"))).toList());
            manifest.put("reverseQuery",query.normalized());manifest.put("catalogMaterialized",true);changed=true;
        }
        if(changed)jdbc.update("update agent_request set manifest=?::jsonb,updated_at=now() where id=?",requests.json(manifest),id);
        return manifest;
    }
    private List<Map<String,Object>> scalarVersions(String[] versions){return jdbc.query("select summary::text,source_file_count from run_version where id=any(?::uuid[]) order by run_id,registration_sequence",(rs,n)->scalarRow(rs.getString(1),rs.getObject(2)),(Object)versions);}
    private Map<String,Object> scalarRow(String json,Object sourceFileCount){var item=scalarSummary(json);item.put("sourceFileCount",sourceFileCount);return item;}
    private Map<String,Object> comparisonContext(UUID id,AgentRequestRepository.Row row,List<RunRef> required,Map<String,Object> reverseQuery,Boolean only){
        require(Boolean.TRUE.equals(only)&&reverseQuery==null,"Comparison requires referencesOnly");
        var attached=entryRefs(row.context().get("comparisonReference"));require(required.size()>=2&&attached.stream().filter(required::contains).toList().equals(required),"Comparison requires ordered explicitly selected references");validate.bulkRefs(required,INVALID);var selected=required;
        if(row.manifest()!=null){require(entryRefs(row.manifest().get("context") instanceof Map<?,?> context?context.get("comparisonReference"):null).equals(required),"Materialized selection cannot change");return row.manifest();}
        @SuppressWarnings("unchecked") var original=(Map<String,Object>)row.context().get("comparisonReference");
        var selectedEntries=((List<?>)original.get("entries")).stream().filter(value->required.contains(mapper.convertValue(((Map<?,?>)value).get("ref"),RunRef.class))).toList();
        Map<String,Object> reference=new LinkedHashMap<>(original);reference.put("entries",selectedEntries);Map<String,Object> updatedContext=new LinkedHashMap<>(row.context());updatedContext.put("comparisonReference",reference);
        var scalars=scalarVersions(selected.stream().map(RunRef::runVersionId).toArray(String[]::new));
        Map<String,Object> manifest=new LinkedHashMap<>();manifest.put("catalogRunRefs",List.of());manifest.put("runs",List.of());manifest.put("referencedRuns",scalars);
        manifest.put("context",Map.of("comparisonReference",reference));manifest.put("createdAt",Instant.now().toString());
        jdbc.update("update agent_request set manifest=?::jsonb,context_snapshot=?::jsonb where id=?",requests.json(manifest),requests.json(updatedContext),id);return manifest;
    }
    private void collectVersions(Object value,Set<String> refs){if(value instanceof Map<?,?> map){if(map.get("runVersionId") instanceof String id)refs.add(id);for(var v:map.values())collectVersions(v,refs);}else if(value instanceof List<?> list)list.forEach(v->collectVersions(v,refs));}
    private Map<String,Object> scalarSummary(String json){
        Map<String,Object> source=requests.read(json),result=new LinkedHashMap<>();
        for(String key:List.of("runId","runVersionId","pressure","sourcePower","biasPower","metrics","units","convergenceStatus","qualityStatus","catalogStatus","registeredAt","presentationScore","note"))if(source.containsKey(key))result.put(key,source.get(key));
        if(source.get("analysis") instanceof Map<?,?> analysis){Map<String,Object> scalars=new LinkedHashMap<>();for(String key:List.of("hasDistribution","strictConvergence","finalResidualMax","electronTemperature","ionTemperature","gasTemperature","absorbedPower","alpha","plasmaResistance","plasmaReactance","dcOffset","peakToPeak","currentDensityPeak","electronDensity","ionDensity","metastableDensity","neutralDensity","ionFluxRaw","metastableFluxRaw","neutralFluxRaw"))if(analysis.containsKey(key))scalars.put(key,analysis.get(key));result.put("analysis",scalars);}
        return result;
    }
    @Transactional public Map<String,Object> needsInput(UUID id,Mutation body){
        var row=fence(id,body.claimGeneration(),body.requestRevision());require(body.pendingInput()!=null,"pendingInput is required");
        validate.text((String)body.pendingInput().get("id"),INVALID,"pendingInput.id");validate.text((String)body.pendingInput().get("message"),INVALID,"pendingInput.message");
        require(requests.json(body.pendingInput()).length()<=20000,"pendingInput is too large");
        var pending=new LinkedHashMap<>(body.pendingInput());
        if("run_selection".equals(pending.get("type"))){
            require(((String)pending.get("id")).length()<=200,"pendingInput.id is too long");
            var session=selections.prepare(id,(String)pending.get("id"),row.context());pending.put("snapshotId",session.id().toString());pending.put("optionsFormat",2);
        }
        jdbc.update("update agent_request set status='NEEDS_INPUT',stage='wait_input',pending_input=?::jsonb,lease_until=null,updated_at=now() where id=?",requests.json(pending),id);return requests.view(requests.get(id,false));
    }
    @Transactional public Map<String,Object> fail(UUID id,Mutation body){
        var current=workspace.lock();var row=fence(id,body.claimGeneration(),body.requestRevision());epochs(row,current);require(body.error()!=null,"error is required");String code=(String)body.error().get("code"),message=(String)body.error().get("message");validate.text(code,INVALID,"error.code");validate.text(message,INVALID,"error.message");require(code.matches("[A-Z_]{1,80}")&&message.length()<=1000,"Invalid public error");
        if(body.partialResult()!=null){
            if(body.partialResult().get("schemaVersion") instanceof Number n&&(n.intValue()==2||n.intValue()==3)){require("compare_runs".equals(row.operationKind()),"Only failed comparisons retain schema-2 partials");require(entryRefs(row.context().get("comparisonReference")).equals(body.usedRunRefs()),"Partial selection mismatch");validate.bulkRefs(body.usedRunRefs(),INVALID);validate.compactValidated(body.partialResult(),INVALID,new HashSet<>(body.usedRunRefs()));new AnswerV2Validator(validate,((Number)body.partialResult().get("schemaVersion")).intValue()==3).comparison(body.partialResult(),body.usedRunRefs(),true);}
            else{require("explain_change".equals(row.operationKind()),"Only a failed change explanation may retain legacy comparison");validatePartialComparison(body.partialResult(),body.usedRunRefs());}}
        jdbc.update("update agent_request set status='FAILED',stage='failed',error=?::jsonb,partial_result=?::jsonb,context_snapshot=null,lease_until=null,pending_input=null,updated_at=now() where id=?",requests.json(Map.of("code",code,"message",message)),requests.json(body.partialResult()),id);requests.purgeTransient(id);return requests.view(requests.get(id,false));
    }
    @Transactional public Map<String,Object> finalizeRequest(UUID id,Mutation body){
        var current=workspace.lock();var row=requests.get(id,true);epochs(row,current);require(body.answer()!=null,"answer is required");
        if("COMPLETED".equals(row.status())){if(!mapper.readTree(requests.json(row.answer())).equals(mapper.valueToTree(body.answer())))conflict("IDEMPOTENCY_CONFLICT","Completed answer cannot change");return requests.view(row);}
        row=fence(id,body.claimGeneration(),body.requestRevision());var answer=body.answer();require(INTENTS.contains(answer.intent()==null?"":answer.intent()),"Invalid answer intent");require(answer.answerSnapshot()!=null,"Answer snapshot is required");require("v1".equals(answer.answerSnapshot().get("implementationId")),"Answer must identify v1");
        if(answer.answerSnapshot().get("schemaVersion") instanceof Number n&&(n.intValue()==2||n.intValue()==3)){
            validate.bulkRefs(answer.usedRunRefs(),INVALID);validate.compactValidated(answer.answerSnapshot(),INVALID,new HashSet<>(answer.usedRunRefs()));new AnswerV2Validator(validate,((Number)answer.answerSnapshot().get("schemaVersion")).intValue()==3).answer(answer,row.question());
            if("compare_runs".equals(answer.answerSnapshot().get("kind")))require(entryRefs(row.context().get("comparisonReference")).equals(answer.usedRunRefs()),"Completed comparison must retain exact selection");
        }else{require((answer.answerSnapshot().get("schemaVersion")==null||answer.answerSnapshot().get("schemaVersion") instanceof Number version&&version.doubleValue()==1),"Unknown answer version");validate.refs(answer.usedRunRefs(),INVALID,false);validate.compact(answer.answerSnapshot(),INVALID,new HashSet<>(answer.usedRunRefs()));}
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
