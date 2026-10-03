package com.kplasma.analysisagent.parser;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.util.List;

/** Percentiles use the full source intensity grid, without interpolation or bin weighting. */
public final class IedWidthCalculator {
    private static final MathContext PRECISION = new MathContext(8, RoundingMode.HALF_EVEN);
    private IedWidthCalculator() {}
    public static Double iedWidth(List<GraphBundle.Point> distribution) {
        if (distribution == null || distribution.isEmpty()) throw invalid("IED is empty");
        double total = 0, previousEnergy = Double.NEGATIVE_INFINITY;
        for (var point : distribution) {
            if (!Double.isFinite(point.x()) || !Double.isFinite(point.y()) || point.y() < 0 || point.x() < previousEnergy)
                throw invalid("IED coordinates and intensities must be finite and ordered; intensities must be nonnegative");
            total += point.y(); previousEnergy = point.x();
        }
        if (!Double.isFinite(total) || total <= 0) throw invalid("IED total intensity must be positive and finite");
        Double p10 = null, p90 = null;
        double cumulative = 0;
        for (var point : distribution) {
            cumulative += point.y();
            if (p10 == null && cumulative >= total * 0.1) p10 = point.x();
            if (cumulative >= total * 0.9) { p90 = point.x(); break; }
        }
        if (p10 == null || p90 == null || !Double.isFinite(p90 - p10)) throw invalid("IED percentile difference is invalid");
        // Construct from the exact binary64 difference; valueOf changes rounding at ties.
        return new BigDecimal(p90 - p10).round(PRECISION).doubleValue();
    }
    private static ParseFailure invalid(String reason) { return ParseFailure.malformed(KPlasmaGraphParser.IED, 0, "iedWidth", reason); }
}
