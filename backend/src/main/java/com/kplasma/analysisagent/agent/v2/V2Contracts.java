package com.kplasma.analysisagent.agent.v2;

import tools.jackson.databind.JsonNode;

import java.util.Set;

/** The composite answer family is independent of the v1 answer schema version. */
public final class V2Contracts {
    private V2Contracts() {}

    public static boolean isSnapshot(JsonNode value) {
        if (value == null || !value.isObject()) return false;
        return "v2".equals(value.path("implementationId").asString())
            && "v2".equals(value.path("graphVersion").asString())
            && value.path("schemaVersion").isIntegralNumber()
            && value.path("schemaVersion").asInt() == 1
            && Set.of("COMPOSITE_ANSWER", "GENERAL_ANSWER").contains(value.path("intent").asString())
            && value.path("question").isString()
            && value.path("answer").isString()
            && value.path("confirmedContext").isObject()
            && value.path("stepResults").isArray()
            && value.path("evidence").isArray()
            && Set.of("COMPLETE", "PARTIAL", "FAILED").contains(value.path("executionStatus").asString())
            && (value.path("hasIncompleteWork").isMissingNode() || value.path("hasIncompleteWork").isBoolean())
            && Set.of("PASS", "ISSUE", "UNAVAILABLE", "SKIPPED").contains(value.path("review").path("status").asString())
            && value.path("review").path("answers").isArray()
            && value.path("budget").isObject();
    }
}
