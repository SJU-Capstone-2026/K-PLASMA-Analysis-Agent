package com.kplasma.analysisagent.workspace;

import com.kplasma.analysisagent.agent.v2.V2ExecutionRepository;
import java.sql.Timestamp;
import java.util.UUID;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@TestPropertySource(properties={"kplasma.agent.worker-token=synthetic-worker-token",
    "AGENT_MODEL_TIMEOUT_SECONDS=137.5"})
class AgentModelTimeoutTest extends WorkspaceTestSupport {
    @Autowired V2ExecutionRepository executions;

    @Test void modelDeadlineUsesConfiguredTimeoutIncludingFractionalSeconds() throws Exception {
        var request = ok("POST", "/api/agent/requests",
            Map.of("text", "IED란?", "stateToken", token(), "graphVersion", "v2"), "model-timeout");
        var requestId = UUID.fromString(request.get("requestId").asString());
        var before = jdbc.queryForObject("select clock_timestamp()", Timestamp.class).toInstant();
        var first = executions.reserveModel(requestId, 1, 0, "PLAN_INITIAL", "initial");
        var after = jdbc.queryForObject("select clock_timestamp()", Timestamp.class).toInstant();
        var deadline = jdbc.queryForObject("select deadline from agent_v2_model_attempt where id=?::uuid",
            Timestamp.class, first.get("attemptId")).toInstant();
        assertThat(deadline).isBetween(before.plusMillis(137_500), after.plusMillis(137_500));
    }
}
