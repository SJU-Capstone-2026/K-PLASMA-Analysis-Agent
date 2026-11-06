package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.RunOutputDto.Output;
import com.kplasma.analysisagent.ingestion.StoredSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** Validates every source row and extracts full graphs for version registration. */
@Component
public class KPlasmaGraphParser {
    public static final String IED = "0d_result/output/IED/Ar+.txt";
    public static final String IAD = "0d_result/output/IAD/Ar+.txt";
    public static final String IEAD = "0d_result/output/IEAD/Ar+.txt";
    public static final String CURRENT = "0d_result/output/CUR/J0h_h.txt";
    public static final String POTENTIAL = "0d_result/output/POT/pot.txt";
    public static final String DENSITY = "0d_result/output/DEN/Ar+.txt";
    private record Header(String value, int line) {}
    record Spec(String type, String gtype, String x, String y, int columns, boolean residual) {}
    static Spec spec(String id) { return switch(id) {case "ied"->IED_SPEC;case "iad"->IAD_SPEC;case "iead"->IEAD_SPEC;case "current"->CURRENT_SPEC;case "potential"->POTENTIAL_SPEC;case "density"->DENSITY_SPEC;case "residual"->RESIDUAL_SPEC;default->throw new IllegalArgumentException("Unknown output");}; }
    public static String path(String id) { return switch(id) {case "ied"->IED;case "iad"->IAD;case "iead"->IEAD;case "current"->CURRENT;case "potential"->POTENTIAL;case "density"->DENSITY;case "residual"->KPlasmaScalarParser.RESIDUAL;default->throw new IllegalArgumentException("Unknown output");}; }
    private static final Spec IED_SPEC = new Spec("IEDs", "1D", "energy (eV)", "IED (a.u.)", 2, false);
    private static final Spec IAD_SPEC = new Spec("IADs", "1D", "angle (degrees)", "IAD (a.u.)", 2, false);
    private static final Spec CURRENT_SPEC = new Spec("Current_density", "1D", "time (rf cycle)", "J0h_h (statampere/cm^2)", 2, false);
    private static final Spec POTENTIAL_SPEC = new Spec("Pot", "1D", "time (rf cycle)", "pot (V)", 2, false);
    private static final Spec IEAD_SPEC = new Spec("IEAD", "2D", "angle (degrees)", "energy (eV)", 3, false);
    private static final Spec DENSITY_SPEC = new Spec("DENSITY", "2D", "time (rf cycle)", "distance (cm)", 3, false);
    private static final Spec RESIDUAL_SPEC = new Spec("residual", "1D", "iteration (#)", "residual (a.u.)", 6, true);
    private static final Pattern INLINE_COMMENT = Pattern.compile("\\s+#.*$");
    private static final Pattern WHITESPACE = Pattern.compile("\\s+");

    private final ComparisonFeatureExtractor extractor;

    public KPlasmaGraphParser(ComparisonFeatureExtractor extractor) {
        this.extractor = extractor;
    }

    public GraphBundle parse(StoredSource source, ParsedScalars scalars, RunRef ref) {
        boolean biasOn = scalars.biasOn();
        List<Output> outputs = new ArrayList<>();
        Double width = null;
        for (var id : ComparisonFeatureExtractor.IDS.stream().sorted().toList()) {
            if (!biasOn && !id.equals("residual")) continue;
            var output = extractor.extract(source, ref, id, biasOn);
            if (!output.metadata().status().equals("AVAILABLE")) {
                throw ParseFailure.incomplete(path(id), "file", "Required source evidence file is missing");
            }
            outputs.add(output);
            if (id.equals("ied")) {
                width = IedWidthCalculator.iedWidth(output.display().samples().stream()
                    .map(point -> new GraphBundle.Point(point.x(), point.y())).toList());
            }
        }
        return new GraphBundle(List.copyOf(outputs), width, biasOn, sourceFiles(source, scalars, biasOn));
    }

    interface Sink { void start(int nx, int ny); void row(int ordinal, double[] columns, int line); }
    static void read(StoredSource source, String path, Spec spec, Sink sink) {
        Map<String, Header> metadata = new HashMap<>();
        int count = 0, nx = 0, ny = 1;
        boolean started = false;
        try (var reader = Files.newBufferedReader(KPlasmaScalarParser.requiredPath(source, path), StandardCharsets.UTF_8)) {
            String text; int line = 0;
            while ((text = reader.readLine()) != null) {
                line++; IniReader.controls(text, path, line, "graph", false); text = text.strip();
                if (text.isEmpty()) continue;
                if (text.startsWith("#")) {
                    int equals = text.indexOf('=');
                    if (equals > 1) {
                        String key = text.substring(1, equals).strip();
                        if (started || metadata.putIfAbsent(key, new Header(text.substring(equals + 1).strip(), line)) != null)
                            throw malformed(path, line, key, "Duplicate or late graph metadata");
                    }
                    continue;
                }
                if (!started) {
                    validate(path, spec, metadata);
                    if (!spec.residual()) {
                        nx = dimension(path, metadata, "nx");
                        if (spec.gtype().equals("2D")) ny = dimension(path, metadata, "ny");
                        // Each numeric row consumes bytes. Refuse huge declarations before allocating axes.
                        if ((long) nx * ny > source.files().get(path).size()) throw malformed(path, 0, "shape", "Declared shape exceeds source byte count");
                    }
                    sink.start(nx, ny); started = true;
                }
                if (text.indexOf('#') >= 0) text = INLINE_COMMENT.matcher(text).replaceFirst("");
                String[] tokens = WHITESPACE.split(text);
                if (tokens.length != spec.columns()) throw malformed(path, line, "columns", "Numeric row has the wrong number of columns");
                double[] columns = new double[tokens.length];
                for (int i = 0; i < tokens.length; i++) columns[i] = IniReader.finite(tokens[i], path, line, "column[" + i + "]");
                if (!spec.residual() && count >= (long) nx * ny) throw malformed(path, line, "shape", "More numeric rows than the declared shape");
                sink.row(count++, columns, line);
            }
        } catch (IOException ex) { throw malformed(path, 0, "file", "Source file is unreadable or invalid UTF-8"); }
        validate(path, spec, metadata);
        if (count == 0) throw ParseFailure.incomplete(path, "rows", "Required graph output is empty");
        if (!spec.residual() && count != (long) nx * ny) throw malformed(path, 0, "shape", "Numeric row count differs from declared shape");
    }
    private static void validate(String path, Spec spec, Map<String, Header> metadata) {
        require(path, metadata, "type", spec.type()); require(path, metadata, "gtype", spec.gtype());
        require(path, metadata, "x", spec.x()); require(path, metadata, "y", spec.y());
        if (spec.residual()) require(path, metadata, "species", "E Ar* Ar+ Ar Te");
        else { dimension(path, metadata, "nx"); if (spec.gtype().equals("2D")) dimension(path, metadata, "ny"); }
    }
    private static void require(String path, Map<String, Header> metadata, String key, String expected) {
        var actual = metadata.get(key);
        if (actual == null || !actual.value().equals(expected)) throw malformed(path, actual == null ? 0 : actual.line(), key, "Missing or incompatible graph metadata");
    }
    private static int dimension(String path, Map<String, Header> metadata, String key) {
        var header = metadata.get(key);
        if (header == null || !header.value().matches("[0-9]+")) throw malformed(path, header == null ? 0 : header.line(), key, "Positive integer dimension required");
        try { int n = Integer.parseInt(header.value()); if (n > 0) return n; }
        catch (NumberFormatException ignored) { }
        throw malformed(path, header.line(), key, "Positive supported integer dimension required");
    }
    private static ParseFailure malformed(String path, int line, String field, String reason) { return ParseFailure.malformed(path, line, field, reason); }
    private static List<RunDto.SourceFile> sourceFiles(StoredSource source, ParsedScalars scalars, boolean biasOn) {
        String[] paths = {KPlasmaScalarParser.INI, KPlasmaScalarParser.SOLVER, KPlasmaScalarParser.RESIDUAL, IED, IAD, IEAD, CURRENT, POTENTIAL, DENSITY};
        String[] types = {"SETTING", "LOG", "LOG", "IED", "IAD", "IEAD", "CURRENT", "POTENTIAL", "DENSITY"};
        List<RunDto.SourceFile> files = new ArrayList<>();
        var conditions = scalars.conditions();
        String root = String.format(Locale.ROOT, "PRS_%02d/Source_%d/Bias_%04d/", (int) conditions.pressure(), (int) conditions.sourcePower(), (int) conditions.biasPower());
        for (int i = 0; i < (biasOn ? 9 : 3); i++) {
            var file = source.files().get(paths[i]);
            if (file == null) throw ParseFailure.incomplete(paths[i], "file", "Required source evidence file is missing");
            long divisor = file.size() < 1048576 ? 1024 : 1048576;
            String size = BigDecimal.valueOf(file.size()).divide(BigDecimal.valueOf(divisor)).setScale(1, RoundingMode.HALF_EVEN).toPlainString()
                    + (divisor == 1024 ? " KB" : " MB");
            files.add(new RunDto.SourceFile(paths[i].substring(paths[i].lastIndexOf('/') + 1), types[i], size, "PARSED", root + paths[i]));
        }
        return List.copyOf(files);
    }
}
