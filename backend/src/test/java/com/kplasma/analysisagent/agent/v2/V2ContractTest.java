package com.kplasma.analysisagent.agent.v2;

import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class V2ContractTest {
    @Test void rejectsUnknownGraphVersion() throws Exception {
        var fixture = new ObjectMapper().readTree(getClass().getResourceAsStream("/v2/contracts.json"));
        assertTrue(V2Contracts.isSnapshot(fixture.get("general_answer")));
        assertFalse(V2Contracts.isSnapshot(new ObjectMapper().valueToTree(
            Map.of("graphVersion", "v1", "implementationId", "v1", "schemaVersion", 3)
        )));
    }
}
