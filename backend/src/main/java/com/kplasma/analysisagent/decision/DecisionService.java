package com.kplasma.analysisagent.decision;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.workspace.*;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
@Service
public class DecisionService {
    private final WorkspaceRepository workspace;private final DecisionRepository repository;private final DecisionValidator validator;private final SnapshotValidator validate;
    public DecisionService(WorkspaceRepository workspace,DecisionRepository repository,DecisionValidator validator,SnapshotValidator validate){this.workspace=workspace;this.repository=repository;this.validator=validator;this.validate=validate;}
    @Transactional public List<DecisionRecord> list(){workspace.lock();return repository.list();}
    @Transactional public DecisionRecord save(long workspaceEpoch,DecisionWrite write,String key) {
        var current=workspace.lock();if(workspaceEpoch!=current.stateToken().workspaceEpoch())throw new IntakeException("STALE_CONTEXT",409,"Workspace has been reset");
        validate.require(write!=null&&write.workspaceEpoch()==workspaceEpoch,"INVALID_DECISION","Decision workspaceEpoch must match");validate.key(key,"INVALID_DECISION");
        // Decisions survive new conversations, so only the workspace epoch scopes their retry keys.
        String replay=workspace.replay(workspaceEpoch,0,"DECISION",key,write);if(replay!=null)return repository.get(replay);
        validator.validate(write);repository.save(write.record());workspace.remember(workspaceEpoch,0,"DECISION",key,write,write.record().reviewId());return repository.get(write.record().reviewId());
    }
}
