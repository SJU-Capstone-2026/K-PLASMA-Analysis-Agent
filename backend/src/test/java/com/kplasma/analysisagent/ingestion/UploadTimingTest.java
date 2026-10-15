package com.kplasma.analysisagent.ingestion;

import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;

class UploadTimingTest {
    @TempDir Path temp;
    @Test void recordsNestedIntervalsWithoutAddingTheirDurationsAndRestoresContext() throws Exception {
        var clock=new AtomicLong(100);
        Path log=temp.resolve("timing.jsonl");
        try(var recorder=new ImportTimingRecorder(log,clock::get)) {
            try(var request=recorder.begin("request","r1")) {
                clock.set(200);
                try(var phase=recorder.measure("file.copy")) {phase.bytes(17);clock.set(400);}
                recorder.bindBatch("batch-1");
                clock.set(900);
            }
            // An uncorrelated pool operation must not become a business SQL sample.
            try(var ignored=recorder.measure("db.execute")) {clock.set(1000);}
        }
        var mapper=new ObjectMapper();
        var events=Files.readAllLines(log).stream().map(mapper::readTree).toList();
        assertThat(events).hasSize(2);
        assertThat(events.get(0).get("phase").asString()).isEqualTo("file.copy");
        assertThat(events.get(0).get("bytes").asLong()).isEqualTo(17);
        assertThat(events.get(0).get("endNs").asLong()-events.get(0).get("startNs").asLong()).isEqualTo(200);
        assertThat(events.get(1).get("phase").asString()).isEqualTo("request");
        assertThat(events.get(1).get("batchId").asString()).isEqualTo("batch-1");
        assertThat(events.get(1).get("endNs").asLong()-events.get(1).get("startNs").asLong()).isEqualTo(800);
    }
    @Test void disabledRecorderDoesNotCreateFiles() {
        try(var recorder=new ImportTimingRecorder(null,System::nanoTime);
            var trace=recorder.begin("job","ignored");var phase=recorder.measure("parse")) {
            phase.bytes(10);
        }
        assertThat(temp.toFile().list()).isEmpty();
    }
}
