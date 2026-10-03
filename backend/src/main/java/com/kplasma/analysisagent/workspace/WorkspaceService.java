package com.kplasma.analysisagent.workspace;

import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class WorkspaceService {
    private static final String INVALID="INVALID_WORKSPACE";
    private static final Set<String> INTENTS=Set.of("FORWARD_LOOKUP","REVERSE_SEARCH","CHANGE_EXPLANATION","CONCEPT_EXPLANATION","RECORD_REUSE","CLARIFICATION","UNSUPPORTED");
    private static final Set<String> UI_KEYS=Set.of("collapsed","openRunIds","runDetailTabs","activeCandidateGroup","continuedRunId","lookupExpanded","selectedCandidateRunId");
    private final WorkspaceRepository repository;
    private final SnapshotValidator validate;
    public WorkspaceService(WorkspaceRepository repository,SnapshotValidator validate){this.repository=repository;this.validate=validate;}
    @Transactional public WorkspaceView load(){return repository.lock();}
    public static void epochs(StateToken submitted,StateToken current) {
        if(submitted==null)throw new IntakeException(INVALID,400,"StateToken is required");
        if(submitted.workspaceEpoch()!=current.workspaceEpoch()||submitted.conversationEpoch()!=current.conversationEpoch())throw new IntakeException("STALE_CONTEXT",409,"Workspace or conversation has changed");
    }
    public static void revision(StateToken submitted,StateToken current) {if(submitted.revision()!=current.revision())throw new IntakeException("STALE_CONTEXT",409,"Workspace revision has changed");}
    @Transactional public WorkspaceView appendTurn(StateToken token,TurnSnapshot turn,String key) {
        var current=repository.lock();epochs(token,current.stateToken());validate.key(key,INVALID);validate.require(turn!=null,INVALID,"Turn is required");
        var payload=new TurnWrite(token,turn);
        // Same epochs + exact payload may replay its original (now old) revision; reply with today's state.
        if(repository.replay(token.workspaceEpoch(),token.conversationEpoch(),"TURN",key,payload)!=null)return current;
        revision(token,current.stateToken());validateTurn(turn);
        UUID id=uuid(turn.id());if(repository.hasTurn(id))throw new IntakeException("TURN_EXISTS",409,"Turn id already exists");
        repository.append(turn);repository.advance();repository.remember(token.workspaceEpoch(),token.conversationEpoch(),"TURN",key,payload,turn.id());return repository.lock();
    }
    private UUID uuid(String id){try{return UUID.fromString(id);}catch(Exception e){throw new IntakeException(INVALID,400,"Turn id must be a UUID");}}
    private void validateTurn(TurnSnapshot turn) {
        uuid(turn.id());validate.instant(turn.askedAt(),INVALID,"askedAt");validate.text(turn.question(),INVALID,"question");validate.require(INTENTS.contains(turn.intent()==null?"":turn.intent()),INVALID,"Invalid intent");
        validate.refs(turn.answerRunRefs(),INVALID,false);if(turn.context()!=null)validate.ref(turn.context(),INVALID);
        validate.require(turn.answerSnapshot()!=null,INVALID,"Answer snapshot is required");Set<RunRef> inventory=new HashSet<>(turn.answerRunRefs());validate.compact(turn.answerSnapshot(),INVALID,inventory);
        if(turn.answerSnapshot().containsKey("candidateRunRefs"))validate.roleRefs(turn.answerSnapshot().get("candidateRunRefs"),INVALID,inventory);
        if(turn.answerSnapshot().get("memoryRequest") instanceof Map<?,?> memory&&memory.containsKey("referenceRunRefs"))validate.roleRefs(memory.get("referenceRunRefs"),INVALID,inventory);
        validate.require(turn.ui()!=null,INVALID,"Turn UI is required");validateUi(turn.ui());
    }
    private void validateUi(TurnUiSnapshot ui){validate.require(ui.openRunIds()!=null&&ui.openRunIds().stream().allMatch(Objects::nonNull),INVALID,"openRunIds requires strings");validate.require(ui.runDetailTabs()!=null&&ui.runDetailTabs().entrySet().stream().allMatch(e->e.getKey()!=null&&e.getValue()!=null),INVALID,"runDetailTabs requires string entries");validate.require(ui.activeCandidateGroup()!=null,INVALID,"activeCandidateGroup requires a string");}
    @Transactional public WorkspaceView updateTurnUi(UUID turnId,StateToken token,Map<String,Object> patch) {
        var current=repository.lock();epochs(token,current.stateToken());revision(token,current.stateToken());
        validate.require(patch!=null,INVALID,"UI patch is required");
        for(var entry:patch.entrySet()) {
            String name=entry.getKey();Object value=entry.getValue();validate.require(UI_KEYS.contains(name),INVALID,"Unknown UI patch key");
            boolean valid=switch(name) {
                case "collapsed","lookupExpanded" -> value instanceof Boolean;
                case "openRunIds" -> value instanceof List<?> list&&list.stream().allMatch(v->v instanceof String);
                case "runDetailTabs" -> value instanceof Map<?,?> map&&map.entrySet().stream().allMatch(e->e.getKey() instanceof String&&e.getValue() instanceof String);
                case "continuedRunId","selectedCandidateRunId" -> value==null||value instanceof String;
                default -> value instanceof String;
            };validate.require(valid,INVALID,"Invalid UI patch value for "+name);
        }
        var turn=current.conversation().turns().stream().filter(t->uuid(t.id()).equals(turnId)).findFirst().orElseThrow(()->new IntakeException("NOT_FOUND",404,"Turn not found"));
        var old=turn.ui();Map<String,String> tabs=new LinkedHashMap<>(old.runDetailTabs());
        if(patch.containsKey("runDetailTabs"))((Map<?,?>)patch.get("runDetailTabs")).forEach((k,v)->tabs.put((String)k,(String)v));
        var ui=new TurnUiSnapshot((Boolean)patch.getOrDefault("collapsed",old.collapsed()),strings(patch.getOrDefault("openRunIds",old.openRunIds())),tabs,(String)patch.getOrDefault("activeCandidateGroup",old.activeCandidateGroup()),(String)patch.getOrDefault("continuedRunId",old.continuedRunId()),(Boolean)patch.getOrDefault("lookupExpanded",old.lookupExpanded()),(String)patch.getOrDefault("selectedCandidateRunId",old.selectedCandidateRunId()));
        repository.updateUi(turnId,ui);repository.advance();return repository.lock();
    }
    private List<String> strings(Object value){return ((List<?>)value).stream().map(String.class::cast).toList();}
    @Transactional public WorkspaceView setReference(StateToken token,ReferenceState reference,RunRef active) {
        var current=repository.lock();epochs(token,current.stateToken());revision(token,current.stateToken());
        if(active!=null)validate.ref(active,INVALID);
        if(reference!=null){validate.require(Set.of("단일 Run","후보 집합").contains(reference.kind()==null?"":reference.kind()),INVALID,"Invalid reference kind");validate.refs(reference.runs(),INVALID,true);validate.require(!reference.runs().isEmpty()&&(!reference.kind().equals("단일 Run")||reference.runs().size()==1),INVALID,"Reference cardinality does not match kind");}
        repository.references(reference,active);repository.advance();return repository.lock();
    }
    @Transactional public WorkspaceView newConversation(StateToken token){return clear(token,false);}
    @Transactional public WorkspaceView reset(StateToken token){return clear(token,true);}
    private WorkspaceView clear(StateToken token,boolean reset){var current=repository.lock();epochs(token,current.stateToken());revision(token,current.stateToken());repository.clear(reset);return repository.lock();}
}
