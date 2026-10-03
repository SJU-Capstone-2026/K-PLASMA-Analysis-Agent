package com.kplasma.analysisagent.parser;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class SourceGridSamplerTest {
    @Test void halfEvenRetainsEndpointsAndRoundsBothTieDirections() {
        assertThat(SourceGridSampler.sampleIndices(6, 3)).containsExactly(0, 2, 5);
        assertThat(SourceGridSampler.sampleIndices(8, 3)).containsExactly(0, 4, 7);
        assertThat(SourceGridSampler.sampleIndices(11, 5)).containsExactly(0, 2, 5, 8, 10);
    }
    @Test void shortAndSingleSourcesAreNotDuplicated() {
        assertThat(SourceGridSampler.sampleIndices(1, 161)).containsExactly(0);
        assertThat(SourceGridSampler.sampleIndices(3, 161)).containsExactly(0, 1, 2);
    }
    @Test void invalidOrAmbiguousSamplingRequestsAreRejected() {
        assertThatThrownBy(() -> SourceGridSampler.sampleIndices(0, 161)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> SourceGridSampler.sampleIndices(3, 1)).isInstanceOf(IllegalArgumentException.class);
    }
}
