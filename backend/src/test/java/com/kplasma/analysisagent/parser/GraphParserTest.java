package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.ingestion.StoredBatch;
import com.kplasma.analysisagent.ingestion.StoredSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;

class GraphParserTest {
    @TempDir Path directory;
    private final KPlasmaGraphParser parser = new KPlasmaGraphParser();

    @Test void biasOffKeepsResidualAndNormalNullsAndOnlyWhitelistedEvidence() throws Exception {
        var source = source(false);
        var graph = parser.parse(source, scalars(false));
        assertThat(graph.iedDistribution()).isEmpty();
        assertThat(graph.iad()).isNull(); assertThat(graph.iead()).isNull();
        assertThat(graph.current()).isNull(); assertThat(graph.potential()).isNull(); assertThat(graph.density()).isNull();
        assertThat(graph.iedWidth()).isNull(); assertThat(graph.hasDistribution()).isFalse();
        assertThat(graph.unavailableReasons()).containsKeys("iedDistribution", "iad", "iead", "current", "potential", "density");
        assertThat(graph.residualTrace()).hasSize(81);
        assertThat(graph.residualTrace().get(80)).isEqualTo(new RunDto.Pair(101, 1010));
        assertThat(graph.sourceFiles()).extracting(RunDto.SourceFile::name).containsExactly("0d_setting.ini", "solver.log", "residual.log");
        assertThat(graph.sourceFiles().get(0).path()).isEqualTo("PRS_02/Source_100/Bias_0000/0d_setting.ini");
        assertThat(graph.sourceFiles().get(0).size()).isEqualTo("1.2 KB");
        assertThat(source.files()).containsKey("0d_result/log/output.log");
    }
    @Test void singleRunAndWrappedUploadsShareCanonicalDisplayPathsWithoutChangingManifest() throws Exception {
        var original = source(true);
        var canonical = parser.parse(original, scalars(true)).sourceFiles();
        for (String root : new String[]{"", "selected-folder/", "outer/PRS_02/Source_100/Bias_0200/"}) {
            var changed = new StoredSource(original.sourceId(), root, original.files(), original.sha256());
            assertThat(parser.parse(changed, scalars(true)).sourceFiles()).isEqualTo(canonical);
            assertThat(changed.relativeRoot()).isEqualTo(root);
            assertThat(changed.files()).isEqualTo(original.files());
        }
    }
    @Test void sourceIndicesPreserveOriginalValuesAndVariableWaveformLengths() throws Exception {
        var result = parser.parse(source(true), scalars(true));
        assertThat(result.hasDistribution()).isTrue(); assertThat(result.unavailableReasons()).isEmpty();
        assertThat(result.iedDistribution()).hasSize(161);
        assertThat(result.iedDistribution().get(1).energy()).isEqualTo(2);
        assertThat(result.iedDistribution().get(160).energy()).isEqualTo(400);
        assertThat(result.iedWidth()).isEqualTo(320);
        assertThat(result.iad()).hasSize(101);
        assertThat(result.current().sourceCount()).isEqualTo(151);
        assertThat(result.current().points()).hasSize(121);
        assertThat(result.current().points().get(1)).isEqualTo(new RunDto.Pair(1, -1));
        assertThat(result.potential().sourceCount()).isEqualTo(301);
        assertThat(result.potential().points().get(1)).isEqualTo(new RunDto.Pair(2, -2));
        assertThat(result.sourceFiles()).extracting(RunDto.SourceFile::type).containsExactly("SETTING", "LOG", "LOG", "IED", "IAD", "IEAD", "CURRENT", "POTENTIAL", "DENSITY");
        assertThat(result.sourceFiles()).extracting(RunDto.SourceFile::status).containsOnly("PARSED");
    }
    @Test void twoDimensionalGridsKeepAngleEnergyOrderAndIrregularDistances() throws Exception {
        var result = parser.parse(source(true), scalars(true));
        assertThat(result.iead().sourceShape()).isEqualTo(new RunDto.Pair(41, 81));
        assertThat(result.iead().angles()).hasSize(31);
        assertThat(result.iead().energies()).hasSize(61);
        assertThat(result.iead().values()).hasSize(1891);
        assertThat(result.iead().values().subList(0, 3)).containsExactly(0.0, 1.0, 3.0);
        assertThat(result.iead().values().get(61)).isEqualTo(1000);
        assertThat(result.iead().values().get(1890)).isEqualTo(40080);
        assertThat(result.density().rows()).hasSize(41);
        assertThat(result.density().sourceShape()).isEqualTo(new RunDto.Pair(51, 31));
        assertThat(result.density().rows().get(1).phase()).isEqualTo(1);
        assertThat(result.density().rows().get(1).distances().subList(0, 4)).containsExactly(0.0, 1.0, 4.0, 9.0);
        assertThat(result.density().rows().get(1).densities().get(30)).isEqualTo(1030);
    }
    @Test void densityPreservesDistancesThatChangeWithPhase() throws Exception {
        var original = source(true);
        String content = grid("DENSITY", "time (rf cycle)", "distance (cm)", 2, 31, true);
        content = content.replace("1 4 1002", "1 5 1002");
        rewrite(original, KPlasmaGraphParser.DENSITY, content);
        var rows = parser.parse(original, scalars(true)).density().rows();
        assertThat(rows.get(0).distances().get(2)).isEqualTo(4);
        assertThat(rows.get(1).distances().get(2)).isEqualTo(5);
        assertThat(rows.get(1).densities().get(2)).isEqualTo(1002);
    }
    @Test void missingBiasOnGraphIsIncompleteRatherThanBiasOffFallback() throws Exception {
        var original = source(true); var files = new HashMap<>(original.files()); files.remove(KPlasmaGraphParser.IAD);
        failure(new StoredSource(UUID.randomUUID(), original.relativeRoot(), files, "synthetic"), "INCOMPLETE", KPlasmaGraphParser.IAD, 0);
    }
    @Test void malformedNumericRowsRetainPhysicalLineAndNeverSkipToValidRow() throws Exception {
        for (String token : new String[]{"NaN", "1e999", "broken", "\u000b1"}) {
            var original = source(true); rewrite(original, KPlasmaGraphParser.IED, one("IEDs", "energy (eV)", "IED (a.u.)", 2, false) + "2 " + token + "\n");
            failure(original, "PARSE_FAILED", KPlasmaGraphParser.IED, 9);
        }
    }
    @Test void metadataUnitsDimensionsAndGridCoordinatesMustAgree() throws Exception {
        var original = source(true);
        rewrite(original, KPlasmaGraphParser.IEAD, grid("IEAD", "angle (degrees)", "energy (eV)", 2, 2, false).replace("1 1 1001\n", ""));
        failure(original, "PARSE_FAILED", KPlasmaGraphParser.IEAD, 0);
        original = source(true); rewrite(original, KPlasmaGraphParser.CURRENT, one("Current_density", "time (rf cycle)", "J0h_h (A/m^2)", 2, true));
        failure(original, "PARSE_FAILED", KPlasmaGraphParser.CURRENT, 4);
        original = source(true); rewrite(original, KPlasmaGraphParser.IEAD, grid("IEAD", "angle (degrees)", "energy (eV)", 2, 2, false).replace("1 1 1001", "1 3 1001"));
        failure(original, "PARSE_FAILED", KPlasmaGraphParser.IEAD, 12);
    }
    @Test void emptyRequiredOutputAndZeroIntensityCannotSucceed() throws Exception {
        var original = source(true); rewrite(original, KPlasmaGraphParser.IED, one("IEDs", "energy (eV)", "IED (a.u.)", 2, false).lines().limit(6).reduce("", (a,b) -> a+b+"\n"));
        failure(original, "INCOMPLETE", KPlasmaGraphParser.IED, 0);
        original = source(true); rewrite(original, KPlasmaGraphParser.IED, one("IEDs", "energy (eV)", "IED (a.u.)", 2, false).replace("0 1", "0 0").replace("1 1", "1 0"));
        failure(original, "PARSE_FAILED", KPlasmaGraphParser.IED, 0);
    }
    private void failure(StoredSource source, String status, String path, int line) {
        assertThatThrownBy(() -> parser.parse(source, scalars(true))).isInstanceOfSatisfying(ParseFailure.class, failure -> {
            assertThat(failure.status()).isEqualTo(status); assertThat(failure.path()).isEqualTo(path); assertThat(failure.line()).isEqualTo(line);
        });
    }
    private ParsedScalars scalars(boolean bias) {
        return new ParsedScalars(new RunDto.Conditions(2,100,bias?200:0), 1, 1, null, null, .01, bias, null);
    }
    private StoredSource source(boolean bias) throws Exception {
        Map<String,String> content = new HashMap<>();
        content.put("0d_setting.ini", "x".repeat(1280)); content.put("0d_result/log/solver.log", "synthetic"); content.put("0d_result/log/output.log", "INFO: Finished!");
        StringBuilder residual = new StringBuilder("# type=residual\n# gtype=1D\n# x=iteration (#)\n# y=residual (a.u.)\n# species=E Ar* Ar+ Ar Te\n");
        for (int i=1;i<=101;i++) residual.append(i+" 0 0 0 -"+i+" -"+(10*i)+"\n");
        content.put("0d_result/log/residual.log", residual.toString());
        if (bias) {
            content.put(KPlasmaGraphParser.IED, one("IEDs", "energy (eV)", "IED (a.u.)", 401, false));
            content.put(KPlasmaGraphParser.IAD, one("IADs", "angle (degrees)", "IAD (a.u.)", 201, false));
            content.put(KPlasmaGraphParser.CURRENT, one("Current_density", "time (rf cycle)", "J0h_h (statampere/cm^2)", 151, true));
            content.put(KPlasmaGraphParser.POTENTIAL, one("Pot", "time (rf cycle)", "pot (V)", 301, true));
            content.put(KPlasmaGraphParser.IEAD, grid("IEAD", "angle (degrees)", "energy (eV)", 41,81,false));
            content.put(KPlasmaGraphParser.DENSITY, grid("DENSITY", "time (rf cycle)", "distance (cm)", 51,31,true));
        }
        Map<String,StoredBatch.File> files = new HashMap<>();
        for(var entry:content.entrySet()) {
            var path=Files.createTempFile(directory,"synthetic-",".txt"); Files.writeString(path,entry.getValue());
            files.put(entry.getKey(),new StoredBatch.File(entry.getKey(),path,Files.size(path),"synthetic","TEXT"));
        }
        return new StoredSource(UUID.randomUUID(),"PRS_02/Source_100/Bias_"+(bias?"0200":"0000"),files,"synthetic");
    }
    private void rewrite(StoredSource source,String path,String content) throws Exception { Files.writeString(source.files().get(path).path(),content); }
    private static String one(String type,String x,String y,int n,boolean negative) {
        var text=new StringBuilder("# type="+type+"\n# gtype=1D\n# x="+x+"\n# y="+y+"\n# nx="+n+"\n# title=synthetic\n");
        for(int i=0;i<n;i++) text.append(i+" "+(negative?-i:1)+"\n"); return text.toString();
    }
    private static String grid(String type,String x,String y,int nx,int ny,boolean irregular) {
        var text=new StringBuilder("# type="+type+"\n# gtype=2D\n# x="+x+"\n# y="+y+"\n# nx="+nx+"\n# ny="+ny+"\n# title=synthetic\n");
        for(int a=0;a<nx;a++) { for(int e=0;e<ny;e++) text.append(a+" "+(irregular?e*e:e)+" "+(a*1000+e)+"\n"); text.append("\n"); }
        return text.toString();
    }
}
