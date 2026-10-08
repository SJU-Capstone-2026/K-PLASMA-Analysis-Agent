package com.kplasma.analysisagent.contract;

import java.util.List;
import java.util.Map;
import com.kplasma.analysisagent.contract.RunDto.RunRef;

/** Original source features are compact; display samples are returned only to the browser. */
public final class RunOutputDto {
    private RunOutputDto() {}
    public record Request(List<RunRef> runRefs,List<String> plotIds) {}
    public record Datum(Double value,String unit,String status,String reason,Map<String,Object> sourceValue) {}
    public record Extremum(double value,double x,Double y,int count) {}
    public record Metadata(RunRef ref,String outputId,String status,String reason,String sourceIntegrity,
            String featurePolicyVersion,String xUnit,String yUnit,String valueUnit,int sourceCount,Map<String,Extremum> extrema) {}
    public record Point(double x,double y) {}
    public record GridRow(double x,List<Double> coordinates,List<Double> values) {}
    public record Display(String kind,List<Point> samples,List<GridRow> rows) {}
    public record Output(Metadata metadata,Map<String,Datum> features,Display display) {
        public Output compact() {return new Output(metadata,features,null);}
    }
    public record Response(List<Output> outputs) {}
}
