package com.kplasma.analysisagent.contract;

import com.fasterxml.jackson.annotation.JsonFormat;
import java.util.List;

/** Scalar search records and complete graph records share the same immutable version identity. */
public final class RunDto {
    private RunDto() {}
    public record RunRef(String runId, String runVersionId) {}
    public record Conditions(double pressure, double sourcePower, double biasPower) {}
    public record Metrics(double ionFlux, double meanIonEnergy, Double iedWidth) {}
    public record Units(String pressure, String sourcePower, String biasPower,
            String ionFlux, String meanIonEnergy, String iedWidth) {}
    @JsonFormat(shape = JsonFormat.Shape.ARRAY)
    public record Pair(double first, double second) {}
    @JsonFormat(shape = JsonFormat.Shape.ARRAY)
    public record DensityRow(double phase, List<Double> distances, List<Double> densities) {}
    public record IedPoint(double energy, double intensity) {}
    public record Iead(List<Double> angles, List<Double> energies, List<Double> values,
            Pair sourceShape, Pair angleRange) {}
    public record Waveform(List<Pair> points, Pair phaseRange, int sourceCount) {}
    public record Density(List<DensityRow> rows, Pair sourceShape) {}
    public record SourceFile(String name, String type, String size, String status, String path) {}
    public record AnalysisScalars(boolean hasDistribution, boolean strictConvergence, double finalResidualMax,
            double electronTemperature, double ionTemperature, double gasTemperature,
            double absorbedPower, double alpha, double plasmaResistance, double plasmaReactance,
            Double dcOffset, Double peakToPeak, double currentDensityPeak,
            double electronDensity, double ionDensity, double metastableDensity, double neutralDensity,
            double ionFluxRaw, double metastableFluxRaw, double neutralFluxRaw) {}
    public record Analysis(boolean hasDistribution, boolean strictConvergence, double finalResidualMax,
            double electronTemperature, double ionTemperature, double gasTemperature,
            double absorbedPower, double alpha, double plasmaResistance, double plasmaReactance,
            Double dcOffset, Double peakToPeak, double currentDensityPeak,
            double electronDensity, double ionDensity, double metastableDensity, double neutralDensity,
            double ionFluxRaw, double metastableFluxRaw, double neutralFluxRaw,
            List<Pair> residualTrace, List<Pair> iad, Iead iead,
            Waveform current, Waveform potential, Density density) {}
    public record Summary(String runId, String runVersionId, double pressure, double sourcePower, double biasPower,
            Metrics metrics, Units units, String convergenceStatus, String qualityStatus,
            String catalogStatus, String registeredAt, double presentationScore, String note, AnalysisScalars analysis) {}
    public record Full(String runId, String runVersionId, double pressure, double sourcePower, double biasPower,
            Metrics metrics, Units units, String convergenceStatus, String qualityStatus,
            String catalogStatus, String registeredAt, double presentationScore, String note, Analysis analysis,
            List<IedPoint> iedDistribution, List<SourceFile> sourceFiles) {}
}
