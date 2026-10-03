package com.kplasma.analysisagent.parser;

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

class ScalarParserTest {
    @TempDir Path directory;
    private final KPlasmaScalarParser parser = new KPlasmaScalarParser();

    @Test void convertsFluxWithoutDisplayRoundingAndScopesRepeatedSpecies() throws Exception {
        var result = parser.parse(source(ini(false), solver(false), residual(), "INFO: Finished!\n", ""));
        assertThat(result.ionFlux()).isEqualTo(1.0);
        assertThat(result.meanIonEnergy()).isEqualTo(12.3456789);
        assertThat(result.analysis().ionDensity()).isEqualTo(30);
        assertThat(result.analysis().neutralFluxRaw()).isEqualTo(70);
        assertThat(result.conditions().sourcePower()).isEqualTo(100);
        assertThat(result.units().ionFlux()).isEqualTo("10¹⁸ m⁻²s⁻¹");
    }
    @Test void finishedRunCanFailStrictThresholdAndFinalTeIsIncluded() throws Exception {
        var result = parser.parse(source(ini(false), solver(false), residual(), "INFO: Finished!", ""));
        assertThat(result.completion().finished()).isTrue();
        assertThat(result.analysis().strictConvergence()).isFalse();
        assertThat(result.analysis().finalResidualMax()).isEqualTo(0.02);
        assertThat(result.conv()).isEqualTo(0.01);
        assertThat(result.completion().finalIteration()).isEqualTo(2);
    }
    @Test void strictThresholdIncludesEquality() throws Exception {
        var result = parser.parse(source(ini(false), solver(false), residual().replace("-2.e-2", "-1.e-2"), "INFO: Finished!", ""));
        assertThat(result.analysis().strictConvergence()).isTrue();
    }
    @Test void biasOffHasNormalMissingBiasSectionsAndDistribution() throws Exception {
        var result = parser.parse(source(ini(false), solver(false), residual(), "INFO: Finished!", "PRS_02/Source_100/Bias_0000/"));
        assertThat(result.analysis().hasDistribution()).isFalse();
        assertThat(result.analysis().dcOffset()).isNull();
        assertThat(result.analysis().peakToPeak()).isNull();
    }
    @Test void biasOnScalarsRemainIndependentOfGraphParsing() throws Exception {
        var result = parser.parse(source(ini(true), solver(true), residual(), "INFO: Finished!", "PRS_02/Source_100/Bias_0200/"));
        assertThat(result.biasOn()).isTrue();
        assertThat(result.analysis().dcOffset()).isEqualTo(-8);
        assertThat(result.analysis().peakToPeak()).isEqualTo(24);
    }
    @Test void preservesKnownRfCycleControlTokenAndRejectsOtherControlCharacters() throws Exception {
        var valid = source(ini(false), solver(false), residual(), "INFO: Finished!", "");
        assertThat(parser.parse(valid).conditions().pressure()).isEqualTo(2);
        failure(source(ini(false).replace("rfCycle=\u0001", "rfCycle=\u0002"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
        failure(source(ini(false).replace("key0=Ar", "key0=Ar\u0001"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
    }
    @Test void rejectsIniSolverAndFolderContradictions() throws Exception {
        failure(source(ini(false), solver(false).replace("Pressure = 2", "Pressure = 4"), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/solver.log");
        failure(source(ini(false), solver(false), residual(), "INFO: Finished!", "PRS_04/Source_100/Bias_0000/"), "PARSE_FAILED", "PRS_04/Source_100/Bias_0000/");
        failure(source(ini(false).replace("Sourceh0=0", "Sourceh0=200"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
    }
    @Test void missingRequiredFileAndFinishMarkerAreIncomplete() throws Exception {
        var valid = source(ini(false), solver(false), residual(), "INFO: Finished!", "");
        Map<String, StoredBatch.File> files = new HashMap<>(valid.files());
        files.remove("0d_setting.ini");
        failure(new StoredSource(UUID.randomUUID(), "", files, "synthetic"), "INCOMPLETE", "0d_setting.ini");
        failure(source(ini(false), solver(false), residual(), "INFO: Finished! extra", ""), "INCOMPLETE", "0d_result/log/output.log");
    }
    @Test void rejectsNonfiniteMalformedRequiredValuesAndUnsupportedFormats() throws Exception {
        for (String token : new String[]{"NaN", "Infinity", "1e999", "1.2 junk"}) {
            failure(source(ini(false).replace("PRS=2", "PRS=" + token), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
        }
        failure(source(ini(false), solver(false).replace("1.e14", "NaN"), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/solver.log");
        failure(source(ini(false), solver(false).replace("RELEASE 8.8.1", "RELEASE 8.8.2"), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/solver.log");
        failure(source(ini(false).replace("rate_Ar.xml", "rate_Xe.xml"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
        failure(source(ini(false).replace("Pulsing=0", "Pulsing=1"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
    }
    @Test void rejectsWrongScalarUnitsDuplicateKeysAndTruncatedResidual() throws Exception {
        failure(source(ini(false), solver(false).replace("(mTorr)", "(Pa)"), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/solver.log");
        failure(source(ini(false).replace("PRS=2", "PRS=2\nPRS=2"), solver(false), residual(), "INFO: Finished!", ""), "PARSE_FAILED", "0d_setting.ini");
        failure(source(ini(false), solver(false), residual() + "3 0.1\n", "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/residual.log");
        failure(source(ini(false), solver(false), residual().replace("-2.e-2", "NaN"), "INFO: Finished!", ""), "PARSE_FAILED", "0d_result/log/residual.log");
    }
    private void failure(StoredSource source, String status, String path) {
        assertThatThrownBy(() -> parser.parse(source)).isInstanceOfSatisfying(ParseFailure.class, failure -> {
            assertThat(failure.status()).isEqualTo(status);
            assertThat(failure.path()).isEqualTo(path);
            assertThat(failure.field()).isNotBlank();
        });
    }
    private StoredSource source(String ini, String solver, String residual, String output, String root) throws Exception {
        Map<String, StoredBatch.File> files = new HashMap<>();
        for (var entry : Map.of("0d_setting.ini", ini, "0d_result/log/solver.log", solver,
                "0d_result/log/residual.log", residual, "0d_result/log/output.log", output).entrySet()) {
            Path path = Files.createTempFile(directory, "synthetic-", ".txt");
            Files.writeString(path, entry.getValue());
            files.put(entry.getKey(), new StoredBatch.File(entry.getKey(), path, Files.size(path), "synthetic", "TEXT"));
        }
        return new StoredSource(UUID.randomUUID(), root, files, "synthetic");
    }
    private static String ini(boolean bias) {
        return """
            # entirely artificial conditions and values
            [DataFile]
            reaction_path=rate_Ar.xml
            unrelated=
            [Option]
            solver=2
            conv=1.e-2 # threshold
            [Pressure]
            PRS=2
            key0=Ar
            [SourcePower]
            Heat=1
            Powerh=1.e2
            Pulsing=0
            [BiasPower]
            Bias=%s
            Sourceh0=%s
            Pulsing0=0
            rfCycle=%s
            """.formatted(bias ? "1" : "0", bias ? "2.e2" : "0", "\u0001");
    }
    private static String solver(boolean bias) {
        return """
            RELEASE 8.8.1, synthetic
            [SIMULATION OPTIONS]
            Source = TCP
            Heating = ON
            SPulsing = OFF
            Bias = %s
            [SOURCE POWER CONDITIONS]
            PowerH = 1.e2 (W)
            %s
            [PREASURE & INLET CONDITIONS]
            Pressure = 2 (mTorr)
            Inlet species = Ar
            [TEMPERATURE PARAMETERS]
            Gas Temp. = 0.03 (eV)
            Electron Temp. = 3.5 (eV)
            Ion Temp. = 0.25 (eV)
            [HEATING PARAMETERS]
            Absorbed power = 80 (W)
            alpha = 0.8 (a.u.)
            Plasma resistance = 0.4 (ohm)
            Plasma reactance = 8 (ohm)
            %s
            [SHEATH PARAMETERS]
            J0h_h = 0 (statampere/cm^2)
            [NUMBER DENSITY]
            Species (#/cm^3)
            ------------------
            E 10
            Ar* 20
            Ar+ 30
            Ar 40
            [ION FLUX AT THE SHEATH EDGE]
            Species (#/cm^2sec)
            ------------------
            Ar+ 1.e14
            [RADICAL FLUX AT THE SHEATH EDGE]
            Species (#/cm^2sec)
            ------------------
            Ar* 60
            Ar 70
            [AVERAGE ION ENERGY AT THE SUBSTRATE]
            Species (eV)
            ------------------
            Ar+ 12.3456789 # precision retained
            """.formatted(bias ? "ON" : "OFF", bias ? "[BIAS POWER CONDITIONS]\nPower1h = 2.e2 (W)" : "",
                bias ? "[BIAS PARAMETERS]\ndc-offset = -8 (V)\npeak-to-peak = 24 (V)" : "");
    }
    private static String residual() {
        return """
            # type=residual
            # gtype=1D
            # x=iteration (#)
            # y=residual (a.u.)
            # species=E Ar* Ar+ Ar Te
            1 1e-1 0 0 0 0
            2 -1e-3 2e-3 3e-3 4e-3 -2.e-2
            """;
    }
}
