package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.workspace.SnapshotValidator;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.*;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class AgentPublicResultProjectionTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private final AgentPublicResultProjection projection=new AgentPublicResultProjection(mapper,new SnapshotValidator(null,null));
    private JsonNode result(JsonNode tool) {
        return mapper.valueToTree(Map.of("executionId","00000000-0000-4000-8000-000000000001","stepId","synthetic-step",
            "outputs",Map.of("toolResult",tool),"runRefs",tool.path("usedRunRefs")));
    }
    @Test void existingArtificialForwardAndComparisonCardContractsSurviveTheProjection() throws Exception {
        var fixture=mapper.readTree(Files.readString(Path.of("../agent/tests/support/answer-v2-wire.json")));
        for(String kind:List.of("forward","comparison")) {
            var tool=fixture.path(kind).path("result");var card=projection.project(List.of(result(tool))).getFirst();
            assertThat(mapper.<JsonNode>valueToTree(card.get("toolResult"))).isEqualTo(tool);
            assertThat(card).containsOnlyKeys("stepId","executionId","runRefs","toolResult");
        }
        var extended=mapper.readTree(Files.readString(Path.of("../agent/tests/support/answer-v3-wire.json"))).path("comparison").path("result");
        assertThat(mapper.<JsonNode>valueToTree(projection.project(List.of(result(extended))).getFirst().get("toolResult"))).isEqualTo(extended);
    }
    @Test void sourceMetadataAndOriginalArraysAreNeverAddedToPublicSearchRunCards() throws Exception {
        var tool=(ObjectNode)mapper.readTree(Files.readString(Path.of("../agent/tests/support/answer-v2-wire.json"))).path("forward").path("result").deepCopy();
        tool.put("rawModelOutput","private");
        for(String key:List.of("run","selectedRun")) {
            var run=(ObjectNode)tool.path(key);run.put("storagePath","/private/source");
            ((ObjectNode)run.path("analysis")).set("density",mapper.valueToTree(List.of(1,2,3)));
        }
        var card=mapper.valueToTree(projection.project(List.of(result(tool))).getFirst());
        assertThat(card.toString()).doesNotContain("rawModelOutput","storagePath","/private/source","density");
    }
    @Test void v2DefaultUnitMetricIdentifiersSurviveWithoutObjectCoercion() throws Exception {
        var tool=(ObjectNode)mapper.readTree(Files.readString(Path.of("../agent/tests/support/answer-v2-wire.json"))).path("forward").path("result").deepCopy();
        tool.set("defaultedUnits",mapper.valueToTree(List.of("ionFlux")));
        var card=mapper.<JsonNode>valueToTree(projection.project(List.of(result(tool))).getFirst());
        assertThat(card.path("toolResult").path("defaultedUnits")).isEqualTo(tool.path("defaultedUnits"));
        tool.set("defaultedUnits",mapper.valueToTree(List.of("privateInternalField")));
        assertThatThrownBy(()->projection.project(List.of(result(tool)))).isInstanceOf(com.kplasma.analysisagent.ingestion.IntakeException.class);
    }
}
