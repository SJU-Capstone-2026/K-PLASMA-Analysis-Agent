package com.kplasma.analysisagent.decision;
import com.kplasma.analysisagent.contract.WorkspaceDto.*;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.workspace.SnapshotValidator;
import java.util.*;
import org.springframework.stereotype.Component;
@Component
public class DecisionValidator {
    private static final String INVALID="INVALID_DECISION";
    private static final Set<String> DECISIONS=Set.of("ADOPT","HOLD","REJECT");
    private final SnapshotValidator validate;
    public DecisionValidator(SnapshotValidator validate){this.validate=validate;}
    private void check(boolean condition,String message){validate.require(condition,INVALID,message);}
    public void validate(DecisionWrite write) {
        check(write!=null&&write.record()!=null,"Decision record is required");var r=write.record();
        validate.text(r.reviewId(),INVALID,"reviewId");check(r.reviewId().length()<=200,"reviewId is too long");validate.instant(r.createdAt(),INVALID,"createdAt");
        validate.text(r.comment(),INVALID,"comment");check(r.authorName()!=null,"authorName is required");check(r.queryText()!=null,"queryText is required");validate.text(r.processMode(),INVALID,"processMode");
        check(DECISIONS.contains(r.decision()==null?"":r.decision()),"Invalid decision");
        validate.ref(r.targetRunRef(),INVALID);check(r.targetRunRef().runId().equals(r.targetRunId()),"targetRunId must match targetRunRef");
        validate.refs(r.comparedRunRefs(),INVALID,true);check(r.comparedRunIds()!=null&&r.comparedRunIds().equals(r.comparedRunRefs().stream().map(RunRef::runId).toList()),"Compared ids and refs must match");
        check(r.comparedRunRefs().size()<=2,"At most two comparison Runs");check(r.comparedRunRefs().stream().noneMatch(ref->ref.runId().equals(r.targetRunId())),"Target cannot be a comparison Run");
        List<RunRef> expected=new ArrayList<>();expected.add(r.targetRunRef());expected.addAll(r.comparedRunRefs());validate.refs(write.runRefs(),INVALID,true);check(new HashSet<>(write.runRefs()).equals(new HashSet<>(expected)),"Write RunRefs must match the decision inventory");
        Set<RunRef> inventory=new HashSet<>(expected);check(r.goals()!=null,"goals are required");validate.compact(r.goals(),INVALID,inventory);
        if(r.version()==null) {
            check(r.id()==null&&r.question()==null&&r.objectives()==null&&r.overallComment()==null&&r.candidates()==null,"REV cannot contain EXP fields");
            check(Set.of("FORWARD","REVERSE","EXPLANATION").contains(r.analysisType()==null?"":r.analysisType()),"Invalid review analysisType");
            check(!"EXPLANATION".equals(r.analysisType())||r.comparedRunRefs().size()==1,"Explanation review requires one verified baseline");
            check(r.constraints()!=null&&r.evidenceKinds()!=null&&r.limitations()!=null&&r.runSnapshots()!=null,"REV metadata and snapshots are required");validate.compact(r.constraints(),INVALID,inventory);
            check(r.runSnapshots().size()==expected.size(),"REV scalar snapshots must match all referenced Runs");
            for(int i=0;i<expected.size();i++){var s=r.runSnapshots().get(i);check(s!=null&&new RunRef(s.runId(),s.runVersionId()).equals(expected.get(i)),"REV snapshot identity must match its RunRef");check(s.conditions()!=null&&s.metrics()!=null&&s.supportingMetrics()!=null,"REV scalar snapshot fields are required");}
        } else {
            check(r.version()==2,"EXP version must be 2");check(r.id()!=null&&r.id().equals(r.reviewId()),"EXP id and reviewId must match");
            check("REVERSE".equals(r.analysisType())&&"GOAL_RECOMMENDATION".equals(r.processMode()),"EXP requires recommendation analysis");
            check(r.constraints()==null&&r.evidenceKinds()==null&&r.limitations()==null&&r.runSnapshots()==null,"EXP cannot contain REV fields");
            check(r.question()!=null&&r.objectives()!=null,"EXP question and objectives are required");validate.text(r.overallComment(),INVALID,"overallComment");check(r.comment().equals(r.overallComment()),"EXP comment must equal overallComment");validate.compact(r.objectives(),INVALID,inventory);
            check(r.candidates()!=null&&r.candidates().size()>=1&&r.candidates().size()<=3,"EXP requires one adoption and at most two extras");
            check(r.candidates().stream().filter(c->c!=null&&"ADOPT".equals(c.decision())).count()==1,"EXP requires exactly one adoption");
            check(r.candidates().size()==expected.size(),"EXP candidates must match the decision inventory");
            for(int i=0;i<expected.size();i++){var c=r.candidates().get(i);check(c!=null&&new RunRef(c.runId(),c.runVersionId()).equals(expected.get(i)),"EXP candidate identity must match its RunRef");check(i==0?"ADOPT".equals(c.decision()):Set.of("HOLD","REJECT").contains(c.decision()==null?"":c.decision()),"First candidate is adopted; extras are HOLD or REJECT");check(c.note()!=null&&c.conditions()!=null&&c.metrics()!=null&&c.objectiveEvaluations()!=null,"EXP candidate scalar snapshot fields are required");validate.compact(c.objectiveEvaluations(),INVALID,inventory);}
            check("ADOPT".equals(r.decision()),"EXP record decision must match adoption");
        }
    }
}
