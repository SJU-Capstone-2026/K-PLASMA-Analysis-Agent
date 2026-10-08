package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.ingestion.StoredBatch;
import com.kplasma.analysisagent.ingestion.StoredSource;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;

class ComparisonFeatureExtractorTest {
    @TempDir Path directory;
    final RunRef ref = new RunRef("SYNTHETIC", "00000000-0000-0000-0000-000000000001");

    @Test void fullSourceExtremaSurviveDisplaySamplingWithExplicitAmplitudeAndNativeUnits() throws Exception {
        var text = new StringBuilder("# type=Current_density\n# gtype=1D\n# x=time (rf cycle)\n# y=J0h_h (statampere/cm^2)\n# nx=1001\n");
        for(int i=0;i<=1000;i++) text.append(i/1000.0).append(' ').append(i==137||i==703?7:i==321?-3:0).append('\n');
        var result = new ComparisonFeatureExtractor().extract(source(KPlasmaGraphParser.CURRENT,text.toString()),ref,"current",true);
        assertThat(result.features().get("current.maximum").value()).isEqualTo(7);
        assertThat(result.features().get("current.minimum").value()).isEqualTo(-3);
        assertThat(result.features().get("current.peakToPeak").value()).isEqualTo(10);
        assertThat(result.features().get("current.halfPeakToPeak").value()).isEqualTo(5);
        assertThat(result.features().get("current.maximumPhase").value()).isEqualTo(.137);
        assertThat(result.metadata().valueUnit()).isEqualTo("statampere/cm²");
        assertThat(result.metadata().sourceCount()).isEqualTo(1001);
        assertThat(result.metadata().extrema().get("maximum").count()).isEqualTo(2);
        assertThat(result.display().samples()).hasSizeLessThanOrEqualTo(163);
        assertThat(result.display().samples()).anySatisfy(p->{assertThat(p.x()).isEqualTo(.137);assertThat(p.y()).isEqualTo(7);});
    }

    @Test void singleSampleIsNotZeroAmplitudeAndBiasOffIsNotZeroWaveform() throws Exception {
        var source=source(KPlasmaGraphParser.POTENTIAL,"# type=Pot\n# gtype=1D\n# x=time (rf cycle)\n# y=pot (V)\n# nx=1\n0 -20\n");
        var extractor=new ComparisonFeatureExtractor();
        assertThat(extractor.extract(source,ref,"potential",true).features().get("potential.halfPeakToPeak").reason()).isEqualTo("INSUFFICIENT_DATA");
        var off=extractor.extract(source,ref,"potential",false);
        assertThat(off.metadata().status()).isEqualTo("UNAVAILABLE");
        assertThat(off.display()).isNull();assertThat(off.features()).isEmpty();
    }

    @Test void residualUsesMaximumAbsoluteSpeciesColumnAndLastOriginalIteration() throws Exception {
        var source=source(KPlasmaScalarParser.RESIDUAL,"# type=residual\n# gtype=1D\n# x=iteration (#)\n# y=residual (a.u.)\n# species=E Ar* Ar+ Ar Te\n1 0 -4 0 0 0\n2 0 0 -9 0 0\n3 .1 0 0 0 0\n");
        var result=new ComparisonFeatureExtractor().extract(source,ref,"residual",false);
        assertThat(result.features().get("residual.maximum").value()).isEqualTo(9);
        assertThat(result.features().get("residual.final").value()).isEqualTo(.1);
        assertThat(result.features().get("residual.finalIteration").value()).isEqualTo(3);
    }

    @Test void gridPeakKeepsOriginalEnergyAngleCoordinatesAndUnknownIntensityUnit() throws Exception {
        var source=source(KPlasmaGraphParser.IEAD,"# type=IEAD\n# gtype=2D\n# x=angle (degrees)\n# y=energy (eV)\n# nx=2\n# ny=2\n-10 100 1\n-10 200 9\n10 100 2\n10 200 3\n");
        var result=new ComparisonFeatureExtractor().extract(source,ref,"iead",true);
        assertThat(result.features().get("iead.peakEnergy").value()).isEqualTo(200);
        assertThat(result.features().get("iead.peakAngle").value()).isEqualTo(-10);
        assertThat(result.features().get("iead.maximum").reason()).isEqualTo("UNIT_NOT_COMPARABLE");
        assertThat(result.display().rows()).hasSize(2);
    }

    private StoredSource source(String name,String text) throws Exception {
        Path path=Files.createTempFile(directory,"synthetic-",".txt");Files.writeString(path,text);
        return new StoredSource(UUID.randomUUID(),"",Map.of(name,new StoredBatch.File(name,path,Files.size(path),"synthetic-file","OUTPUT")),"synthetic-source");
    }
}
