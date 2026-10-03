package com.kplasma.analysisagent.contract;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class ContractSerializationTest {
    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test void fullRunRoundTripsTheSharedTypescriptWireFixtureIncludingGraphTuples() throws Exception {
        var fixture = mapper.readTree(Files.readString(Path.of("../agent/tests/support/contract-wire.json")));
        for (var mode : new String[]{"on", "off"}) {
            var original = fixture.get(mode);
            var full = mapper.treeToValue(original, RunDto.Full.class);
            assertTrue(original.equals((left, right) -> left.isNumber() && right.isNumber()
                    ? Double.compare(left.doubleValue(), right.doubleValue()) : left.equals(right) ? 0 : 1,
                    mapper.valueToTree(full)), "Graph structure, scalar values, nulls and field names must survive JSON serialization");
            assertEquals("00000000-0000-4000-8000-000000000001", full.runVersionId());
            if (mode.equals("off")) {
                assertNull(full.metrics().iedWidth());
                assertNull(full.analysis().dcOffset());
                assertNull(full.analysis().density());
                assertTrue(full.iedDistribution().isEmpty());
            } else {
                assertEquals(1.0, full.analysis().density().rows().getFirst().phase());
                assertEquals(3.0, full.analysis().density().rows().getFirst().densities().getFirst());
                assertEquals(2.0, full.analysis().current().points().getFirst().second());
            }
        }
    }
    @Test void summaryRoundTripsAllSharedScalarFieldsWithoutAnyGraphArrays() throws Exception {
        var fixture = mapper.readTree(Files.readString(Path.of("../agent/tests/support/contract-wire.json")));
        for (var mode : new String[]{"summaryOn", "summaryOff"}) {
            var original = fixture.get(mode);
            var summary = mapper.treeToValue(original, RunDto.Summary.class);
            assertTrue(original.equals((left, right) -> left.isNumber() && right.isNumber()
                    ? Double.compare(left.doubleValue(), right.doubleValue()) : left.equals(right) ? 0 : 1,
                    mapper.valueToTree(summary)));
        }
    }
    @Test void reviewOmitsVersionAndExperimentKeepsVersionTwo() throws Exception {
        var reviewJson = "{\"reviewId\":\"REV-artificial\",\"targetRunId\":\"SYNTHETIC\",\"comparedRunIds\":[],\"decision\":\"HOLD\",\"comment\":\"artificial\",\"authorName\":\"tester\",\"createdAt\":\"2000-01-01T00:00:00Z\",\"analysisType\":\"FORWARD\",\"processMode\":\"CONDITION_LOOKUP\",\"constraints\":[],\"goals\":[],\"queryText\":\"\",\"evidenceKinds\":[],\"limitations\":[],\"runSnapshots\":[],\"targetRunRef\":{\"runId\":\"SYNTHETIC\",\"runVersionId\":\"00000000-0000-4000-8000-000000000001\"},\"comparedRunRefs\":[]}";
        var review = mapper.readValue(reviewJson, WorkspaceDto.DecisionRecord.class);
        assertEquals(mapper.readTree(reviewJson), mapper.valueToTree(review));
        var experiment = (tools.jackson.databind.node.ObjectNode) mapper.readTree(reviewJson).deepCopy();
        experiment.put("version", 2);
        var value = mapper.treeToValue(experiment, WorkspaceDto.DecisionRecord.class);
        assertEquals(2, mapper.valueToTree(value).get("version").intValue());
    }
}
