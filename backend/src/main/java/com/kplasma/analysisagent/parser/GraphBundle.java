package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
import java.util.List;
import java.util.Map;

/** Validated graphs and display evidence; the full original manifest stays in storage. */
public record GraphBundle(List<RunDto.IedPoint> iedDistribution, List<RunDto.Pair> iad,
        RunDto.Iead iead, RunDto.Waveform current, RunDto.Waveform potential,
        RunDto.Density density, List<RunDto.Pair> residualTrace, Double iedWidth,
        boolean hasDistribution, Map<String,String> unavailableReasons, List<RunDto.SourceFile> sourceFiles) {
    public record Point(double x, double y) {}
}
