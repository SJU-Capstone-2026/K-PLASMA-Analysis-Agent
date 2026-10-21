package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;

@Service
public class RunSelectionService {
    private final RunSelectionRepository options;
    private final AgentRequestRepository requests;
    private final JdbcTemplate jdbc;
    public RunSelectionService(RunSelectionRepository options,AgentRequestRepository requests,JdbcTemplate jdbc){this.options=options;this.requests=requests;this.jdbc=jdbc;}
    public record Change(String pendingInputId,long expectedRequestRevision,long expectedSelectionRevision,String operation,List<String> keys,String query,String baselineKey) {}
    private record Scope(UUID request,String pending,long revision,RunSelectionRepository.Session session) {}
    static void require(boolean value,String message){if(!value)throw new IntakeException("INVALID_AGENT_REQUEST",400,message);}
    static void stale(String message){throw new IntakeException("STALE_REQUEST",409,message);}
    static String query(String value){String text=value==null?"":value;require(text.length()<=256,"Search is too long");return text;}
    private void lock(UUID id){
        jdbc.queryForObject("select id from workspace where id=1 for update",Integer.class);
        if(jdbc.queryForList("select id from agent_request where id=? for update",UUID.class,id).isEmpty())throw new IntakeException("NOT_FOUND",404,"Agent request not found");
    }
    private Scope scope(UUID id,String pending){
        require(pending!=null&&pending.length()<=200,"Invalid pending input id");
        var rows=jdbc.queryForList("""
            select r.request_revision from agent_request r join workspace w on w.id=1
            where r.id=? and r.status='NEEDS_INPUT' and r.pending_input->>'type'='run_selection'
            and r.pending_input->>'id'=? and r.workspace_epoch=w.workspace_epoch and r.conversation_epoch=w.conversation_epoch
            """,id,pending);
        if(rows.isEmpty())stale("실험 선택 요청이 변경되었습니다. 화면을 새로고침해 주세요.");
        var session=options.find(id,pending);
        if(session==null){
            // One-time conversion of an old frozen JSON list. Never refreeze from today's catalogue.
            lock(id);var row=requests.get(id,false);
            if(!"NEEDS_INPUT".equals(row.status())||!Objects.equals(row.pending().get("id"),pending))stale("Selection changed");
            require(row.context()!=null&&row.context().get("comparisonOptions") instanceof Map<?,?> old&&old.get("options") instanceof List<?>,"Frozen options are unavailable");
            session=freeze(id,pending,row.context());
        }
        return new Scope(id,pending,((Number)rows.getFirst().get("request_revision")).longValue(),session);
    }
    public RunSelectionRepository.Session freeze(UUID id,String pending,Map<String,Object> context){
        var session=options.create(id,pending,context==null?Map.of():context);
        Map<String,Object> updated=new LinkedHashMap<>(context==null?Map.of():context);
        updated.put("comparisonOptions",Map.of("format",2,"snapshotId",session.id().toString(),"pendingInputId",pending));
        jdbc.update("update agent_request set context_snapshot=?::jsonb where id=?",requests.json(updated),id);return session;
    }
    private Map<String,Object> metadata(Scope scope){
        var s=scope.session();Map<String,Object> result=new LinkedHashMap<>();
        result.put("format",2);result.put("requestId",scope.request().toString());result.put("requestRevision",scope.revision());result.put("pendingInputId",scope.pending());
        result.put("snapshotId",s.id().toString());result.put("selectionRevision",s.revision());result.put("baselineKey",s.baseline());result.put("totalCount",s.total());return result;
    }
    private List<?> decode(String encoded,Scope scope,String query,String sort,boolean selected){
        if(encoded==null||encoded.isEmpty())return null;
        require(encoded.length()<=4000,"Cursor is too long");
        try{
            var cursor=requests.read(new String(Base64.getUrlDecoder().decode(encoded),StandardCharsets.UTF_8));
            require(Objects.equals(cursor.get("snapshot"),scope.session().id().toString())&&Objects.equals(cursor.get("pending"),scope.pending())&&((Number)cursor.get("revision")).longValue()==scope.revision()&&Objects.equals(cursor.get("query"),query)&&Objects.equals(cursor.get("sort"),sort)&&Objects.equals(cursor.get("selected"),selected),"Cursor belongs to a different search");
            var after=(List<?>)cursor.get("after");require(after.size()==(selected?1:3),"Invalid cursor");
            if(selected){require(after.getFirst() instanceof Number,"Invalid selection cursor");}
            else{require(after.get(0) instanceof String&&after.get(1) instanceof String,"Invalid cursor");UUID.fromString((String)after.get(2));}
            return after;
        }catch(Exception e){throw new IntakeException("INVALID_AGENT_REQUEST",400,"Invalid or mismatched page cursor");}
    }
    private Map<String,Object> page(Scope scope,String query,String sort,String cursor,int size,boolean selected){
        require(size>=1&&size<=100,"pageSize must be 1..100");require(Set.of("ascending","descending").contains(sort),"Unknown sort order");
        var rows=options.page(scope.session().id(),query,sort.equals("descending"),decode(cursor,scope,query,sort,selected),size+1,selected);
        boolean more=rows.size()>size;String next=null;if(more){rows=new ArrayList<>(rows.subList(0,size));var last=rows.getLast();var ref=(Map<?,?>)last.get("ref");
            List<?> after=selected?List.of(last.get("_ordinal")):List.of(last.get("_sort"),ref.get("runId"),ref.get("runVersionId"));
            next=Base64.getUrlEncoder().withoutPadding().encodeToString(requests.json(Map.of("snapshot",scope.session().id().toString(),"pending",scope.pending(),"revision",scope.revision(),"query",query,"sort",sort,"selected",selected,"after",after)).getBytes(StandardCharsets.UTF_8));}
        rows.forEach(row->{row.remove("_sort");row.remove("_ordinal");});
        var result=metadata(scope);result.put("options",rows);result.put("hasMore",more);result.put("nextCursor",next);return result;
    }
    @Transactional(isolation=Isolation.REPEATABLE_READ) public Map<String,Object> page(UUID id,String pending,String query,String sort,String cursor,int size){return page(scope(id,pending),query(query),sort,cursor,size,false);}
    @Transactional(isolation=Isolation.REPEATABLE_READ) public Map<String,Object> count(UUID id,String pending,String query){var scope=scope(id,pending);var result=metadata(scope);String q=query(query);result.put("matchingCount",q.isEmpty()?scope.session().total():options.count(scope.session().id(),q));return result;}
    @Transactional(isolation=Isolation.REPEATABLE_READ) public Map<String,Object> selected(UUID id,String pending,String cursor,int size){
        var scope=scope(id,pending);var result=page(scope,"","ascending",cursor,size,true);result.putAll(options.selectedCounts(scope.session().id()));return result;
    }
    @Transactional public Map<String,Object> change(UUID id,Change change,String key){
        require(key!=null&&!key.isBlank()&&key.length()<=200,"Idempotency-Key is required");
        lock(id);var scope=scope(id,change.pendingInputId());var s=scope.session();
        String payload=requests.json(change);
        var previous=jdbc.queryForList("select payload=?::jsonb same from agent_run_selection_mutation where snapshot_id=? and idempotency_key=?",payload,s.id(),key);
        if(!previous.isEmpty()){
            if(!Boolean.TRUE.equals(previous.getFirst().get("same")))throw new IntakeException("IDEMPOTENCY_CONFLICT",409,"Selection key belongs to another mutation");
            return selected(id,change.pendingInputId(),null,30);
        }
        if(change.expectedRequestRevision()!=scope.revision()||change.expectedSelectionRevision()!=s.revision())stale("다른 화면에서 선택이 변경되었습니다. 선택 목록을 다시 불러와 주세요.");
        String operation=String.valueOf(change.operation());String q=query(change.query());
        switch(operation){
            case "add","remove" -> {
                var keys=change.keys();require(keys!=null&&!keys.isEmpty()&&keys.size()<=100&&new HashSet<>(keys).size()==keys.size()&&keys.stream().allMatch(k->k!=null&&k.length()<=80),"Choose 1..100 unique aliases");
                var found=options.chosen(s.id(),keys);require(found.size()==keys.size(),"Unknown Run alias");
                if(operation.equals("add"))require(found.stream().allMatch(o->Boolean.TRUE.equals(o.get("selectable"))),"Run is unavailable");
                jdbc.update("update agent_run_selection_option set selected=? where snapshot_id=? and alias=any(?::text[])",operation.equals("add"),s.id(),keys.toArray(String[]::new));
            }
            case "search","all" -> jdbc.update("""
                update agent_run_selection_option o set selected=true where snapshot_id=? and not selected and selectable
                and exists(select 1 from run_version v where v.id=o.run_version_id)
                and search_text like ? escape E'\\\\'
                """,s.id(),RunSelectionRepository.pattern(operation.equals("all")?"":q));
            case "clear" -> jdbc.update("update agent_run_selection_option set selected=false where snapshot_id=? and selected",s.id());
            case "baseline" -> {
                String baseline=change.baselineKey();if(baseline!=null){require(baseline.length()<=80,"Invalid baseline");var found=options.chosen(s.id(),List.of(baseline));require(found.size()==1&&Boolean.TRUE.equals(found.getFirst().get("selected"))&&Boolean.TRUE.equals(found.getFirst().get("selectable")),"Baseline must be a selected available Run");}
                jdbc.update("update agent_run_selection set baseline_key=? where id=?",baseline,s.id());
            }
            default -> require(false,"Unknown selection operation");
        }
        jdbc.update("update agent_run_selection s set revision=revision+1,baseline_key=case when exists(select 1 from agent_run_selection_option o where o.snapshot_id=s.id and o.alias=s.baseline_key and o.selected) then baseline_key else null end where id=?",s.id());
        jdbc.update("insert into agent_run_selection_mutation(snapshot_id,idempotency_key,payload) values (?,?,?::jsonb)",s.id(),key,payload);
        return selected(id,change.pendingInputId(),null,30);
    }
    /** Called inside the existing workspace -> request resume transaction. */
    public Map<String,Object> resolve(UUID id,String pending,Map<String,Object> input,boolean baselineRequired){
        var scope=scope(id,pending);var s=scope.session();List<String> keys=null;Object baseline=s.baseline();
        if(input.containsKey("runKeys")){
            require(input.keySet().stream().allMatch(Set.of("type","runKeys","baselineKey")::contains),"Unexpected selection field");
            require(input.get("runKeys") instanceof List<?>,"runKeys are required");var raw=(List<?>)input.get("runKeys");
            require(raw.size()>=2&&new HashSet<>(raw).size()==raw.size()&&raw.stream().allMatch(k->k instanceof String str&&str.length()<=80),"Select at least two unique Runs");
            keys=raw.stream().map(String.class::cast).toList();baseline=input.get("baselineKey");
        }else{
            require(input.keySet().stream().allMatch(Set.of("type","snapshotId","selectionRevision")::contains),"Unexpected selection field");
            require(Objects.equals(input.get("snapshotId"),s.id().toString())&&input.get("selectionRevision") instanceof Number,"Invalid selection snapshot");
            if(((Number)input.get("selectionRevision")).longValue()!=s.revision())stale("Selection changed before resume");
        }
        var chosen=options.chosen(s.id(),keys);require(chosen.size()>=2&&(keys==null||chosen.size()==keys.size()),"Select at least two unique Runs");
        require(chosen.stream().allMatch(o->Boolean.TRUE.equals(o.get("selectable"))),"선택한 실험이 삭제되었거나 비교할 수 없습니다. 선택을 수정해 주세요.");
        if(keys!=null){Map<String,Integer> order=new HashMap<>();for(int i=0;i<keys.size();i++)order.put(keys.get(i),i);chosen.sort(Comparator.comparingInt(o->order.get(o.get("key"))));}
        Object baselineKey=baseline;require(baselineKey==null||chosen.stream().anyMatch(o->Objects.equals(o.get("key"),baselineKey)),"Baseline must be selected");require(!baselineRequired||baselineKey!=null,"Baseline is required");
        List<Map<String,Object>> entries=new ArrayList<>();for(var option:chosen){Map<String,Object> origin=new LinkedHashMap<>();origin.put("kind","hitl");origin.put("turnId",null);origin.put("groupId",null);origin.put("pendingInputId",pending);entries.add(Map.of("key",option.get("key"),"ref",option.get("ref"),"origin",origin));}
        Map<String,Object> reference=new LinkedHashMap<>();reference.put("entries",entries);reference.put("baselineKey",baselineKey);return reference;
    }
    public void finish(UUID id){options.delete(id);}
}
