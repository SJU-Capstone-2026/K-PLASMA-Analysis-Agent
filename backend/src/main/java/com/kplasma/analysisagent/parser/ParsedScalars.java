package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;

/** Raw scalar evidence only; graph validation and READY/VERIFIED belong to later stages. */
public record ParsedScalars(RunDto.Conditions conditions, double ionFlux, double meanIonEnergy,
        RunDto.AnalysisScalars analysis, RunDto.Units units, double conv, boolean biasOn,
        Completion completion) {
    public record Completion(boolean finished, String outputPath, int outputLine,
            double finalIteration, String residualPath, int residualLine) {}
}
