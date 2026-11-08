package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.RunOutputDto.*;
import com.kplasma.analysisagent.ingestion.StoredSource;
import java.util.*;
import org.springframework.stereotype.Component;

/** One source pass for full-grid extrema and every original display point. */
@Component
public class ComparisonFeatureExtractor {
    public static final String POLICY="source-features-1";
    public static final Set<String> IDS=Set.of("ied","iad","iead","current","potential","density","residual");
    public Output unavailable(RunRef ref,String id,String reason,String integrity) {
        return new Output(new Metadata(ref,id,"UNAVAILABLE",reason,integrity,POLICY,"","","",0,Map.of()),Map.of(),null);
    }
    public Output extract(StoredSource source,RunRef ref,String id,boolean biasOn) {
        if(!IDS.contains(id))throw new IllegalArgumentException("Unknown output");
        if(!biasOn&&!id.equals("residual"))return unavailable(ref,id,"BIAS_OFF",source.sha256());
        String path=KPlasmaGraphParser.path(id);
        if(!source.files().containsKey(path))return unavailable(ref,id,"SOURCE_MISSING",source.sha256());
        boolean grid=id.equals("iead")||id.equals("density"),residual=id.equals("residual");
        String xUnit=switch(id){case "ied"->"eV";case "iad","iead"->"°";case "residual"->"iteration";default->"RF cycle";};
        String yUnit=id.equals("iead")?"eV":id.equals("density")?"cm":"";
        String unit=switch(id){case "current"->"statampere/cm²";case "potential"->"V";case "iead","density"->"원본 단위 미지정";default->"a.u.";};
        class Collector implements KPlasmaGraphParser.Sink {
            int ny,count,maxCount,minCount;
            double previousX=Double.NEGATIVE_INFINITY,previousY=Double.NEGATIVE_INFINITY,blockX;
            double max=Double.NEGATIVE_INFINITY,min=Double.POSITIVE_INFINITY,lastX,lastValue,maxX,minX,maxY,minY;
            byte[] firstAxisHash;java.security.MessageDigest axisDigest;final java.nio.ByteBuffer axisBytes=java.nio.ByteBuffer.allocate(8);
            List<Point> samples=new ArrayList<>();List<GridRow> rows=new ArrayList<>();
            List<Double> coords=new ArrayList<>(),values=new ArrayList<>();
            public void start(int a,int b){
                ny=b;
                if(grid&&id.equals("density")&&b!=31)fail(0,"Unsupported density grid");
                if(id.equals("iead"))try{axisDigest=java.security.MessageDigest.getInstance("SHA-256");}catch(java.security.NoSuchAlgorithmException ex){throw new IllegalStateException(ex);}
            }
            void fail(int line,String reason){throw ParseFailure.malformed(path,line,"axis",reason);}
            public void row(int ordinal,double[] c,int line){
                double x=c[0],y=c[1],v=grid?c[2]:y;
                if(residual){v=0;for(int i=1;i<c.length;i++)v=Math.max(v,Math.abs(c[i]));}
                if(grid){
                    int a=ordinal/ny,b=ordinal%ny;
                    if(b==0){if(x<=previousX)fail(line,"Outer axis must increase");previousX=x;blockX=x;previousY=Double.NEGATIVE_INFINITY;}
                    if(x!=blockX||y<=previousY)fail(line,"Grid coordinates must preserve source order");previousY=y;
                    if(axisDigest!=null){axisBytes.clear();axisBytes.putLong(Double.doubleToLongBits(y==0?0:y));axisDigest.update(axisBytes.array());if(b==ny-1){byte[] hash=axisDigest.digest();if(a==0)firstAxisHash=hash;else if(!Arrays.equals(hash,firstAxisHash))fail(line,"IEAD energy axes differ");}}
                    if(v<0)fail(line,"Negative distribution intensity");
                    coords.add(y);values.add(v);
                    if(b==ny-1){rows.add(new GridRow(x,List.copyOf(coords),List.copyOf(values)));coords.clear();values.clear();}
                }else{
                    if(x<=previousX||residual&&(x<=0||x!=Math.rint(x)))fail(line,"Source axis must increase");previousX=x;
                    if((id.equals("ied")||id.equals("iad"))&&v<0)fail(line,"Negative distribution intensity");
                    samples.add(new Point(x,v));
                }
                if(v>max){max=v;maxX=x;maxY=y;maxCount=1;}else if(v==max)maxCount++;
                if(v<min){min=v;minX=x;minY=y;minCount=1;}else if(v==min)minCount++;
                lastX=x;lastValue=v;count++;
            }
            Output result(){
                Map<String,Datum> f=new LinkedHashMap<>();
                f.put(id+".maximum",grid
                    ? new Datum(null,unit,"UNAVAILABLE","UNIT_NOT_COMPARABLE",Map.of("value",max,"unit",unit))
                    : datum(max,unit,null));
                if(id.equals("current")||id.equals("potential")){
                    f.put(id+".minimum",datum(min,unit,null));
                    f.put(id+".peakToPeak",datum(max-min,unit,count<2?"INSUFFICIENT_DATA":null));
                    f.put(id+".halfPeakToPeak",datum((max-min)/2,unit,count<2?"INSUFFICIENT_DATA":null));
                    f.put(id+".maximumPhase",datum(maxX,xUnit,null));f.put(id+".minimumPhase",datum(minX,xUnit,null));
                }else if(id.equals("ied"))f.put("ied.peakEnergy",datum(maxX,xUnit,null));
                else if(id.equals("iad"))f.put("iad.peakAngle",datum(maxX,xUnit,null));
                else if(id.equals("iead")){f.put("iead.peakAngle",datum(maxX,xUnit,null));f.put("iead.peakEnergy",datum(maxY,yUnit,null));}
                else if(id.equals("density")){f.put("density.maximumPhase",datum(maxX,xUnit,null));f.put("density.maximumDistance",datum(maxY,yUnit,null));}
                else {f.put("residual.maximumIteration",datum(maxX,xUnit,null));f.put("residual.final",datum(lastValue,unit,null));f.put("residual.finalIteration",datum(lastX,xUnit,null));}
                var extrema=Map.of("maximum",new Extremum(max,maxX,grid?maxY:null,maxCount),"minimum",new Extremum(min,minX,grid?minY:null,minCount));
                return new Output(new Metadata(ref,id,"AVAILABLE",null,source.sha256(),POLICY,xUnit,yUnit,unit,count,extrema),Map.copyOf(f),new Display(grid?"grid":"line",List.copyOf(samples),List.copyOf(rows)));
            }
        }
        var collector=new Collector();KPlasmaGraphParser.read(source,path,KPlasmaGraphParser.spec(id),collector);return collector.result();
    }
    private static Datum datum(double value,String unit,String reason){
        if(!Double.isFinite(value))reason="NUMERIC_OVERFLOW";
        return new Datum(reason==null?value:null,unit,reason==null?"AVAILABLE":"UNAVAILABLE",reason,null);
    }
}
