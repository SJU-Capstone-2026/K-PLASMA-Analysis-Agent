package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.contract.RunOutputDto.Output;
import java.util.List;

/** Complete graph outputs, derived width, and the retained source manifest. */
public record GraphBundle(List<Output> outputs, Double iedWidth,
        boolean hasDistribution, List<RunDto.SourceFile> sourceFiles) {
    public record Point(double x, double y) {}
}
