package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class GraphVersionPolicyTest {
    @Test void deploymentDefaultsAndClaimsNeverImplicitlyEnableAnotherRuntime() {
        var cloud = new GraphVersionPolicy("v1,v2", "v1");
        assertEquals("v1", cloud.resolve(null, null));
        assertThrows(IntakeException.class, () -> cloud.resolve(null, "v3"));
        assertThrows(IntakeException.class, () -> cloud.workerVersions(List.of("v2_localLLM")));
        var local = new GraphVersionPolicy("v2_localLLM", "v2_localLLM");
        assertEquals("v2_localLLM", local.resolve(null, null));
        assertThrows(IntakeException.class, () -> local.resolve(null, "v1"));
        assertThrows(IntakeException.class, () -> local.workerVersions(null));
    }

    @Test void sharedDeploymentPreservesTheSelectedAndPinnedGraph() {
        var shared = new GraphVersionPolicy("v1,v2,v2_localLLM", "v2_localLLM");
        assertEquals("v2_localLLM", shared.resolve(null, null));
        for (String version : List.of("v1", "v2", "v2_localLLM"))
            assertEquals(version, shared.resolve(null, version));
        assertThrows(IntakeException.class, () -> shared.resolve("v2", "v2_localLLM"));
    }

    @Test void invalidDeploymentsFailAtStartup() {
        for (String versions : List.of("", "unknown", "v1,", "v2,v2_localLLM", "v1,v2,v3"))
            assertThrows(IllegalArgumentException.class, () -> new GraphVersionPolicy(versions, "v1"));
        assertThrows(IllegalArgumentException.class, () -> new GraphVersionPolicy("v2_localLLM", "v1"));
    }
}
