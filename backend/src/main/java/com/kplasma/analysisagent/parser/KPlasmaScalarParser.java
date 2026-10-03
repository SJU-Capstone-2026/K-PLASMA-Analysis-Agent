package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.ingestion.StoredSource;
import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** Supported input is the fixed Ar / TCP / CW / release 8.8.1 format. */
@Component
public class KPlasmaScalarParser {
    public static final String INI = "0d_setting.ini";
    public static final String SOLVER = "0d_result/log/solver.log";
    public static final String OUTPUT = "0d_result/log/output.log";
    public static final String RESIDUAL = "0d_result/log/residual.log";
    private static final Pattern FOLDER = Pattern.compile("(?:^|/)PRS_(\\d+)/Source_(\\d+)/Bias_(\\d+)(?:/|$)");

    public ParsedScalars parse(StoredSource source) {
        var ini = new IniReader(INI, read(source, INI));
        var solver = new SolverLogReader(SOLVER, read(source, SOLVER));
        supported(ini, solver);
        double pressure = ini.number("Pressure", "PRS");
        double sourcePower = ini.number("SourcePower", "Powerh");
        double biasPower = ini.number("BiasPower", "Sourceh0");
        double biasFlag = ini.number("BiasPower", "Bias");
        if ((biasFlag != 0 && biasFlag != 1) || (biasFlag == 0) != (biasPower == 0))
            throw ParseFailure.malformed(INI, ini.line("BiasPower", "Bias"), "BiasPower.Bias", "Bias flag and power disagree");
        boolean biasOn = biasFlag == 1;
        equal(pressure, solver.number("PREASURE & INLET CONDITIONS", "Pressure", "mTorr"), SOLVER, "pressure");
        equal(sourcePower, solver.number("SOURCE POWER CONDITIONS", "PowerH", "W"), SOLVER, "sourcePower");
        equalText(biasOn ? "ON" : "OFF", solver.text("SIMULATION OPTIONS", "Bias"), SOLVER, "Bias");
        if (biasOn || solver.hasSection("BIAS POWER CONDITIONS"))
            equal(biasPower, solver.number("BIAS POWER CONDITIONS", "Power1h", "W"), SOLVER, "biasPower");
        if (!biasOn && solver.hasSection("BIAS PARAMETERS"))
            throw ParseFailure.malformed(SOLVER, 0, "BIAS PARAMETERS", "Bias-off contains bias scalar output");
        checkGrid(pressure, new double[]{2, 4, 6, 8, 10}, "pressure");
        checkGrid(sourcePower, new double[]{100, 200, 300, 400, 500}, "sourcePower");
        checkGrid(biasPower, new double[]{0, 200, 400, 600, 800, 1000}, "biasPower");
        var folder = FOLDER.matcher(source.relativeRoot());
        if (folder.find()) {
            equal(pressure, IniReader.finite(folder.group(1), source.relativeRoot(), 0, "pressure"), source.relativeRoot(), "pressure");
            equal(sourcePower, IniReader.finite(folder.group(2), source.relativeRoot(), 0, "sourcePower"), source.relativeRoot(), "sourcePower");
            equal(biasPower, IniReader.finite(folder.group(3), source.relativeRoot(), 0, "biasPower"), source.relativeRoot(), "biasPower");
        }
        double conv = ini.number("Option", "conv");
        if (conv <= 0) throw ParseFailure.malformed(INI, ini.line("Option", "conv"), "Option.conv", "Convergence threshold must be positive");
        int finishLine = finishLine(source);
        var last = finalResidual(source);
        double ionFluxRaw = solver.species("ION FLUX AT THE SHEATH EDGE", "Ar+", "#/cm^2sec");
        // hasDistribution is set only after Task 6 validates the required graph bundle.
        var analysis = new RunDto.AnalysisScalars(false, last.maximum() <= conv, last.maximum(),
                solver.number("TEMPERATURE PARAMETERS", "Electron Temp.", "eV"),
                solver.number("TEMPERATURE PARAMETERS", "Ion Temp.", "eV"),
                solver.number("TEMPERATURE PARAMETERS", "Gas Temp.", "eV"),
                solver.number("HEATING PARAMETERS", "Absorbed power", "W"),
                solver.number("HEATING PARAMETERS", "alpha", "a.u."),
                solver.number("HEATING PARAMETERS", "Plasma resistance", "ohm"),
                solver.number("HEATING PARAMETERS", "Plasma reactance", "ohm"),
                biasOn ? solver.number("BIAS PARAMETERS", "dc-offset", "V") : null,
                biasOn ? solver.number("BIAS PARAMETERS", "peak-to-peak", "V") : null,
                solver.number("SHEATH PARAMETERS", "J0h_h", "statampere/cm^2"),
                solver.species("NUMBER DENSITY", "E", "#/cm^3"),
                solver.species("NUMBER DENSITY", "Ar+", "#/cm^3"),
                solver.species("NUMBER DENSITY", "Ar*", "#/cm^3"),
                solver.species("NUMBER DENSITY", "Ar", "#/cm^3"), ionFluxRaw,
                solver.species("RADICAL FLUX AT THE SHEATH EDGE", "Ar*", "#/cm^2sec"),
                solver.species("RADICAL FLUX AT THE SHEATH EDGE", "Ar", "#/cm^2sec"));
        return new ParsedScalars(new RunDto.Conditions(pressure, sourcePower, biasPower), ionFluxRaw * 1e-14,
                solver.species("AVERAGE ION ENERGY AT THE SUBSTRATE", "Ar+", "eV"), analysis,
                new RunDto.Units("mTorr", "W", "W", "10¹⁸ m⁻²s⁻¹", "eV", "eV"), conv, biasOn,
                new ParsedScalars.Completion(true, OUTPUT, finishLine, last.iteration(), RESIDUAL, last.line()));
    }
    private static void supported(IniReader ini, SolverLogReader solver) {
        equalText("rate_Ar.xml", ini.text("DataFile", "reaction_path"), INI, "DataFile.reaction_path");
        equalText("Ar", ini.text("Pressure", "key0"), INI, "Pressure.key0");
        equal(2, ini.number("Option", "solver"), INI, "Option.solver");
        equal(1, ini.number("SourcePower", "Heat"), INI, "SourcePower.Heat");
        equal(0, ini.number("SourcePower", "Pulsing"), INI, "SourcePower.Pulsing");
        equal(0, ini.number("BiasPower", "Pulsing0"), INI, "BiasPower.Pulsing0");
        equalText("\u0001", ini.text("BiasPower", "rfCycle"), INI, "BiasPower.rfCycle");
        solver.requireRelease();
        equalText("TCP", solver.text("SIMULATION OPTIONS", "Source"), SOLVER, "Source");
        equalText("ON", solver.text("SIMULATION OPTIONS", "Heating"), SOLVER, "Heating");
        equalText("OFF", solver.text("SIMULATION OPTIONS", "SPulsing"), SOLVER, "SPulsing");
        equalText("Ar", solver.text("PREASURE & INLET CONDITIONS", "Inlet species"), SOLVER, "Inlet species");
    }
    private static void equal(double expected, double actual, String path, String field) {
        if (expected != actual) throw ParseFailure.malformed(path, 0, field, "Unsupported format or contradictory condition");
    }
    private static void equalText(String expected, String actual, String path, String field) {
        if (!expected.equals(actual)) throw ParseFailure.malformed(path, 0, field, "Unsupported format or contradictory condition");
    }
    private static void checkGrid(double value, double[] supported, String field) {
        for (double candidate : supported) if (candidate == value) return;
        throw ParseFailure.malformed(INI, 0, field, "Condition outside the supported fixed grid");
    }
    static Path requiredPath(StoredSource source, String relative) {
        var file = source.files().get(relative);
        if (file == null) throw ParseFailure.incomplete(relative, "file", "Required source file is missing");
        return file.path();
    }
    private static List<String> read(StoredSource source, String relative) {
        try { return Files.readAllLines(requiredPath(source, relative), StandardCharsets.UTF_8); }
        catch (IOException ex) { throw ParseFailure.malformed(relative, 0, "file", "Source file is unreadable or invalid UTF-8"); }
    }
    private static int finishLine(StoredSource source) {
        try (var reader = Files.newBufferedReader(requiredPath(source, OUTPUT), StandardCharsets.UTF_8)) {
            String text; int line = 0, finished = 0;
            while ((text = reader.readLine()) != null) {
                line++;
                IniReader.controls(text, OUTPUT, line, "completion", false);
                if (text.strip().equals("INFO: Finished!")) finished = line;
            }
            if (finished == 0) throw ParseFailure.incomplete(OUTPUT, "completion", "Engine completion marker is missing");
            return finished;
        } catch (IOException ex) { throw ParseFailure.malformed(OUTPUT, 0, "file", "Source file is unreadable or invalid UTF-8"); }
    }
    private record Residual(double iteration, double maximum, int line) {}
    private static Residual finalResidual(StoredSource source) {
        Map<String, String> metadata = new HashMap<>();
        Residual last = null;
        try (BufferedReader reader = Files.newBufferedReader(requiredPath(source, RESIDUAL), StandardCharsets.UTF_8)) {
            String text; int line = 0;
            while ((text = reader.readLine()) != null) {
                line++;
                IniReader.controls(text, RESIDUAL, line, "residual", false);
                text = text.strip();
                if (text.isEmpty()) continue;
                if (text.startsWith("#")) {
                    int equals = text.indexOf('=');
                    if (equals > 1) {
                        String key = text.substring(1, equals).strip(), value = text.substring(equals + 1).strip();
                        if (last != null || metadata.putIfAbsent(key, value) != null)
                            throw ParseFailure.malformed(RESIDUAL, line, key, "Duplicate or late residual metadata");
                    }
                    continue;
                }
                String[] columns = text.replaceFirst("\\s+#.*$", "").split("\\s+");
                if (columns.length != 6) throw ParseFailure.malformed(RESIDUAL, line, "columns", "Expected iteration and five residual columns");
                double iteration = IniReader.finite(columns[0], RESIDUAL, line, "iteration");
                if (iteration <= 0 || iteration != Math.rint(iteration) || last != null && iteration <= last.iteration())
                    throw ParseFailure.malformed(RESIDUAL, line, "iteration", "Residual iterations must increase and be positive integers");
                double maximum = 0;
                for (int i = 1; i < columns.length; i++) maximum = Math.max(maximum, Math.abs(IniReader.finite(columns[i], RESIDUAL, line, "residual[" + i + "]")));
                last = new Residual(iteration, maximum, line);
            }
        } catch (IOException ex) { throw ParseFailure.malformed(RESIDUAL, 0, "file", "Source file is unreadable or invalid UTF-8"); }
        for (var expected : Map.of("type", "residual", "gtype", "1D", "x", "iteration (#)", "y", "residual (a.u.)", "species", "E Ar* Ar+ Ar Te").entrySet())
            equalText(expected.getValue(), metadata.get(expected.getKey()), RESIDUAL, expected.getKey());
        if (last == null) throw ParseFailure.incomplete(RESIDUAL, "rows", "Residual output is empty");
        return last;
    }
}
