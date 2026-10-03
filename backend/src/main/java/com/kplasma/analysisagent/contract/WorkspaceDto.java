package com.kplasma.analysisagent.contract;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;
import com.kplasma.analysisagent.contract.RunDto.*;

/** Persisted snapshots contain compact answer objects and immutable version references, never graph payloads. */
public final class WorkspaceDto {
    private WorkspaceDto() {}
    public record StateToken(long workspaceEpoch, long conversationEpoch, long revision) {}
    public record TurnUiSnapshot(boolean collapsed, List<String> openRunIds,
            Map<String, String> runDetailTabs, String activeCandidateGroup, String continuedRunId,
            boolean lookupExpanded, String selectedCandidateRunId) {}
    public record TurnSnapshot(String id, String askedAt, String question, String intent,
            RunRef context, List<RunRef> answerRunRefs, Map<String, Object> answerSnapshot, TurnUiSnapshot ui) {}
    public record ReferenceState(String kind, List<RunRef> runs) {}
    public record Conversation(int version, RunRef activeRun, List<TurnSnapshot> turns) {}
    public record WorkspaceView(StateToken stateToken, Conversation conversation, ReferenceState candidateReference) {}
    public record SupportingMetrics(double electronDensity, double electronTemperature) {}
    public record RunSnapshot(String runId, String runVersionId, Conditions conditions,
            Metrics metrics, SupportingMetrics supportingMetrics) {}
    public record CandidateSnapshot(String runId, String runVersionId, String decision, String note,
            Conditions conditions, Metrics metrics, List<Map<String, Object>> objectiveEvaluations) {}
    /** REV: version absent; EXP: version=2. Persistence validates the union and one adoption/up to two extras. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record DecisionRecord(String reviewId, String id, Integer version, String targetRunId,
            List<String> comparedRunIds, RunRef targetRunRef, List<RunRef> comparedRunRefs,
            String decision, String comment, String authorName, String createdAt, String analysisType,
            String processMode, List<Map<String, Object>> constraints, List<Map<String, Object>> goals,
            String queryText, List<String> evidenceKinds, List<String> limitations, List<RunSnapshot> runSnapshots,
            String question, List<Map<String, Object>> objectives, String overallComment,
            List<CandidateSnapshot> candidates) {}
    public record DecisionWrite(long workspaceEpoch, DecisionRecord record, List<RunRef> runRefs) {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AgentRequest(String text, RunRef baseline, List<RunRef> candidateReferences, Map<String, Object> clarification) {}
    public record AgentResponse(String intent, String status, List<RunRef> candidates, Map<String, Object> explanation,
            Map<String, Object> answerSnapshot, List<RunRef> usedRunRefs) {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Error(String code, String message, String field, Map<String, Object> details, String requestId) {}
}
