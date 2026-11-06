package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class AgentPublicEventPayloadTest {
    @Test void planReviewActivityIsDistinctFromFinalInterpretationReviewWithoutLeakingItsPlan() {
        var activity = Map.<String,Object>of("activityId", "review-plan-1", "code", "PLAN_REVIEW", "phase", "started");
        assertThat(AgentPublicEvents.validate("activity", activity)).isEqualTo(activity);
        assertThatThrownBy(() -> AgentPublicEvents.validate("activity", Map.of(
            "activityId", "review-plan-1", "code", "PLAN_REVIEW", "phase", "completed", "reviewInput", Map.of())))
            .isInstanceOf(IntakeException.class);
    }

    @Test void publicEventsRejectUnknownFieldsAndUnboundedOrInternalContent() {
        assertThatThrownBy(() -> AgentPublicEvents.validate("activity", Map.of(
            "activityId", "r0:plan", "code", "PLAN", "phase", "started", "rawPlan", "private")))
            .isInstanceOf(IntakeException.class);
        assertThatThrownBy(() -> AgentPublicEvents.validate("answer.delta", Map.of(
            "streamId", "draft-1", "answerRevision", 1, "blockId", "paragraphs:0", "chunkIndex", 0,
            "text", "x".repeat(8193)))).isInstanceOf(IntakeException.class);
        assertThatThrownBy(() -> AgentPublicEvents.validate("request.state", Map.of("status", "COMPLETED")))
            .isInstanceOf(IntakeException.class);
    }

    @Test void activitiesAndAnswerStartsHaveOnlyDocumentedPublicFields() {
        var activity = Map.<String,Object>of("activityId", "r0:compare:start", "code", "COMPARE_RUNS",
            "phase", "started", "runCount", 2, "metricIds", List.of("pressure", "ionFlux"));
        assertThat(AgentPublicEvents.validate("activity", activity)).isEqualTo(activity);
        assertThat(AgentPublicEvents.validate("answer.start", Map.of("streamId", "draft-1", "mode", "general")))
            .containsEntry("rewrite", false).doesNotContainKey("answerRevision");
    }

    @Test void resetsInvalidateOnlyTheDraftAndRewritesReplaceItsBlocks() {
        var projection = new AgentPublicEvents.Projection();
        projection.apply("results.ready", Map.of("resultRevision", 3), 3, "2000-01-01T00:00:00Z");
        projection.apply("answer.start", Map.of("streamId", "one", "answerRevision", 1, "mode", "interpretation", "rewrite", false), 4, "2000-01-01T00:00:01Z");
        projection.apply("answer.delta", Map.of("streamId", "one", "answerRevision", 1, "blockId", "interpretations:0", "text", "draft", "chunkIndex", 0), 5, "2000-01-01T00:00:02Z");
        projection.apply("answer.reset", Map.of("streamId", "one", "answerRevision", 1, "reason", "REWRITE"), 6, "2000-01-01T00:00:03Z");
        assertThat(projection.answer()).containsEntry("status", "interrupted").containsEntry("blocks", List.of());
        projection.apply("answer.start", Map.of("streamId", "two", "answerRevision", 2, "mode", "interpretation", "rewrite", true), 7, "2000-01-01T00:00:04Z");
        projection.apply("answer.delta", Map.of("streamId", "one", "answerRevision", 1, "blockId", "interpretations:0", "text", "late", "chunkIndex", 1), 8, "2000-01-01T00:00:05Z");
        projection.apply("answer.delta", Map.of("streamId", "two", "answerRevision", 2, "blockId", "interpretations:0", "text", "revised", "chunkIndex", 0), 9, "2000-01-01T00:00:06Z");
        assertThat(projection.answer()).containsEntry("status", "rewriting")
            .containsEntry("blocks", List.of(Map.of("id", "interpretations:0", "text", "revised")));
        assertThat(projection.resultRevision()).isEqualTo(3L);
    }
}
