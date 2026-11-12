package com.kplasma.analysisagent.agent.v3;

import com.kplasma.analysisagent.agent.v2.V2Contracts;
import com.kplasma.analysisagent.agent.v2.GraphVersionPolicy;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class V3ContractTest {
    @Test void identitiesAndModeAreRequiredWithoutBroadeningV2() {
        var mapper=new ObjectMapper();
        var fixture=mapper.readTree(getClass().getResourceAsStream("/v2/contracts.json"));
        ObjectNode v3=(ObjectNode)fixture.get("general_answer").deepCopy();
        assertTrue(V2Contracts.isSnapshot(v3));
        v3.put("implementationId","v3");v3.put("graphVersion","v3");
        assertFalse(V3Contracts.isSnapshot(v3));
        v3.set("executionMode",mapper.valueToTree(V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",false))));
        assertTrue(V3Contracts.isSnapshot(v3));
        assertFalse(V2Contracts.isSnapshot(v3));
        ((ObjectNode)v3.path("executionMode")).put("ragEnabled",true);
        assertFalse(V3Contracts.isSnapshot(v3));
    }
    @Test void v3IsExplicitlyRoutedAndCannotChangePinnedConversation() {
        assertEquals("v1",GraphVersionPolicy.resolve(null,null));
        assertEquals("v3",GraphVersionPolicy.resolve(null,"v3"));
        assertEquals(List.of("v3"),GraphVersionPolicy.workerVersions(List.of("v3")));
        assertThrows(RuntimeException.class,()->GraphVersionPolicy.resolve("v2","v3"));
    }
}
