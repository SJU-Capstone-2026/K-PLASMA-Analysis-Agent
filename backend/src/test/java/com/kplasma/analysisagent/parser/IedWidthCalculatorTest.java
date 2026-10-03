package com.kplasma.analysisagent.parser;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class IedWidthCalculatorTest {
    @Test void percentilesChooseOriginalGridPointsWithoutInterpolationOrBinWeighting() {
        assertThat(IedWidthCalculator.iedWidth(List.of(new GraphBundle.Point(0, 1), new GraphBundle.Point(2, 8), new GraphBundle.Point(100, 1)))).isEqualTo(2.0);
    }
    @Test void roundsExactBinary64DifferenceToEightSignificantDigits() {
        assertThat(IedWidthCalculator.iedWidth(List.of(new GraphBundle.Point(0, 1), new GraphBundle.Point(1.23456795, 9)))).isEqualTo(1.2345679);
    }
    @Test void invalidDistributionsDoNotProduceInventedWidths() {
        for (var values : List.of(List.<GraphBundle.Point>of(), List.of(new GraphBundle.Point(0, 0)),
                List.of(new GraphBundle.Point(0, -1)), List.of(new GraphBundle.Point(Double.NaN, 1)),
                List.of(new GraphBundle.Point(0, Double.POSITIVE_INFINITY)),
                List.of(new GraphBundle.Point(0, Double.MAX_VALUE), new GraphBundle.Point(1, Double.MAX_VALUE))))
            assertThatThrownBy(() -> IedWidthCalculator.iedWidth(values)).isInstanceOf(ParseFailure.class);
    }
}
