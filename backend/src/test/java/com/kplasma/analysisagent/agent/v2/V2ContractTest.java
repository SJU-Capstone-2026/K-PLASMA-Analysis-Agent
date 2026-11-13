package com.kplasma.analysisagent.agent.v2;

import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class V2ContractTest {
    @Test void compositeHeadersMustMatchAndTheV2GuardStaysStrict() throws Exception {
        var fixture = new ObjectMapper().readTree(getClass().getResourceAsStream("/v2/contracts.json"));
        for (String version : java.util.List.of("v3", "v2_localLLM")) {
            var snapshot = (ObjectNode) fixture.get("general_answer").deepCopy();
            snapshot.put("implementationId", version).put("graphVersion", version);
            assertTrue(V2Contracts.isCompositeSnapshot(snapshot));
            assertFalse(V2Contracts.isSnapshot(snapshot));
            snapshot.put("graphVersion", "v2");
            assertFalse(V2Contracts.isCompositeSnapshot(snapshot));
            snapshot.put("graphVersion", version);
            snapshot.remove("implementationId");
            assertFalse(V2Contracts.isCompositeSnapshot(snapshot));
        }
    }

    @Test void rejectsUnknownGraphVersion() throws Exception {
        var fixture = new ObjectMapper().readTree(getClass().getResourceAsStream("/v2/contracts.json"));
        assertTrue(V2Contracts.isSnapshot(fixture.get("general_answer")));
        assertFalse(V2Contracts.isSnapshot(new ObjectMapper().valueToTree(
            Map.of("graphVersion", "v1", "implementationId", "v1", "schemaVersion", 3)
        )));
    }
}
