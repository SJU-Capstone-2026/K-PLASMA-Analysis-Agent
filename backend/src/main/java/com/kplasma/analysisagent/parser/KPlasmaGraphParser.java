package com.kplasma.analysisagent.parser;

import com.kplasma.analysisagent.contract.RunDto;
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
import org.springframework.stereotype.Component;

/** Validates supported source grids and selects original rows without inventing coordinates. */
@Component
public class KPlasmaGraphParser {
    public static final String IED = "0d_result/output/IED/Ar+.txt";
    public static final String IAD = "0d_result/output/IAD/Ar+.txt";
    public static final String IEAD = "0d_result/output/IEAD/Ar+.txt";
    public static final String CURRENT = "0d_result/output/CUR/J0h_h.txt";
    public static final String POTENTIAL = "0d_result/output/POT/pot.txt";
    public static final String DENSITY = "0d_result/output/DEN/Ar+.txt";
    private static final String BIAS_OFF = "Bias-off Run에는 해당 쉬스 분포 출력이 저장되지 않았습니다.";
    private record Header(String value, int line) {}
    private record Row(double x, double y) {}
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

    public GraphBundle parse(StoredSource source, ParsedScalars scalars) {
        var residual = pairs(sample(one(source, KPlasmaScalarParser.RESIDUAL, RESIDUAL_SPEC), 81));
        if (!scalars.biasOn()) {
            var reasons = Map.of("iedDistribution", BIAS_OFF, "iad", BIAS_OFF, "iead", BIAS_OFF,
                    "current", BIAS_OFF, "potential", BIAS_OFF, "density", BIAS_OFF);
            return new GraphBundle(List.of(), null, null, null, null, null, residual, null, false,
                    reasons, sourceFiles(source, scalars, false));
        }
        var rawIed = one(source, IED, IED_SPEC);
        double width = IedWidthCalculator.iedWidth(rawIed.stream().map(r -> new GraphBundle.Point(r.x(), r.y())).toList());
        var ied = sample(rawIed, 161).stream().map(r -> new RunDto.IedPoint(r.x(), r.y())).toList();
        var iad = pairs(sample(one(source, IAD, IAD_SPEC), 101));
        var ieadGrid = grid(source, IEAD, IEAD_SPEC, 31, 61);
        var iead = new RunDto.Iead(ieadGrid.x(), ieadGrid.y(), ieadGrid.values(),
                new RunDto.Pair(ieadGrid.nx(), ieadGrid.ny()), ieadGrid.range());
        var current = waveform(one(source, CURRENT, CURRENT_SPEC));
        var potential = waveform(one(source, POTENTIAL, POTENTIAL_SPEC));
        var densityGrid = grid(source, DENSITY, DENSITY_SPEC, 41, Integer.MAX_VALUE);
        List<RunDto.DensityRow> rows = new ArrayList<>();
        for (int i = 0; i < densityGrid.x().size(); i++) rows.add(new RunDto.DensityRow(densityGrid.x().get(i),
                densityGrid.rowY().get(i), List.copyOf(densityGrid.values().subList(i * densityGrid.ny(), (i + 1) * densityGrid.ny()))));
        var density = new RunDto.Density(List.copyOf(rows), new RunDto.Pair(densityGrid.nx(), densityGrid.ny()));
        return new GraphBundle(ied, iad, iead, current, potential, density, residual, width, true,
                Map.of(), sourceFiles(source, scalars, true));
    }
    private static RunDto.Waveform waveform(List<Row> raw) {
        return new RunDto.Waveform(pairs(sample(raw, 121)), new RunDto.Pair(raw.getFirst().x(), raw.getLast().x()), raw.size());
    }
    private static List<RunDto.Pair> pairs(List<Row> raw) { return raw.stream().map(r -> new RunDto.Pair(r.x(), r.y())).toList(); }
    private static <T> List<T> sample(List<T> raw, int limit) {
        List<T> result = new ArrayList<>();
        for (int index : SourceGridSampler.sampleIndices(raw.size(), limit)) result.add(raw.get(index));
        return List.copyOf(result);
    }
    private static List<Row> one(StoredSource source, String path, Spec spec) {
        List<Row> rows = new ArrayList<>();
        read(source, path, spec, new Sink() {
            public void start(int nx, int ny) {}
            public void row(int ordinal, double[] columns, int line) {
                double x = columns[0], y = columns[1];
                if (!rows.isEmpty() && x <= rows.getLast().x() || spec.residual() && (x <= 0 || x != Math.rint(x)))
                    throw malformed(path, line, "x", "Source axis must increase; iterations must be positive integers");
                if (spec.residual()) { y = 0; for (int i = 1; i < columns.length; i++) y = Math.max(y, Math.abs(columns[i])); }
                if ((spec == IED_SPEC || spec == IAD_SPEC) && y < 0) throw malformed(path, line, "intensity", "Negative distribution intensity");
                rows.add(new Row(x, y));
            }
        });
        return List.copyOf(rows);
    }
    private record Grid(int nx, int ny, List<Double> x, List<Double> y, List<Double> values, List<List<Double>> rowY, RunDto.Pair range) {}
    private static Grid grid(StoredSource source, String path, Spec spec, int maxX, int maxY) {
        class GridSink implements Sink {
            int nx, ny, selectedX, selectedY;
            int[] xs, ys;
            double[] xAxis, yAxis;
            List<Double> values = new ArrayList<>();
            List<List<Double>> rowY = new ArrayList<>();
            public void start(int nx, int ny) {
                if (spec == DENSITY_SPEC && ny != 31) throw malformed(path, 0, "ny", "Supported density grid requires 31 original distances");
                this.nx = nx; this.ny = ny;
                xs = SourceGridSampler.sampleIndices(nx, maxX); ys = SourceGridSampler.sampleIndices(ny, maxY);
                xAxis = new double[nx]; yAxis = new double[ny];
            }
            public void row(int ordinal, double[] columns, int line) {
                int a = ordinal / ny, e = ordinal % ny;
                if (a >= nx) throw malformed(path, line, "shape", "More numeric rows than the declared shape");
                if (e == 0) {
                    xAxis[a] = columns[0];
                    if (a > 0 && xAxis[a] <= xAxis[a - 1]) throw malformed(path, line, "x", "Outer source axis must increase");
                } else if (columns[0] != xAxis[a]) throw malformed(path, line, "x", "Outer coordinate changed within a block");
                if (a == 0 || spec == DENSITY_SPEC) {
                    yAxis[e] = columns[1];
                    if (e > 0 && yAxis[e] <= yAxis[e - 1]) throw malformed(path, line, "y", "Inner source axis must increase");
                } else if (columns[1] != yAxis[e]) throw malformed(path, line, "y", "Inner source coordinates differ between blocks");
                if (selectedX < xs.length && a == xs[selectedX] && selectedY < ys.length && e == ys[selectedY]) {
                    values.add(columns[2]); selectedY++;
                }
                if (e == ny - 1 && selectedX < xs.length && a == xs[selectedX]) {
                    if (spec == DENSITY_SPEC) {
                        List<Double> distances = new ArrayList<>();
                        for (int index : ys) distances.add(yAxis[index]);
                        rowY.add(List.copyOf(distances));
                    }
                    selectedX++; selectedY = 0;
                }
            }
            Grid result() {
                List<Double> x = new ArrayList<>(), y = new ArrayList<>();
                for (int index : xs) x.add(xAxis[index]); for (int index : ys) y.add(yAxis[index]);
                return new Grid(nx, ny, List.copyOf(x), List.copyOf(y), List.copyOf(values), List.copyOf(rowY), new RunDto.Pair(xAxis[0], xAxis[nx - 1]));
            }
        }
        var sink = new GridSink(); read(source, path, spec, sink); return sink.result();
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
                String[] tokens = text.replaceFirst("\\s+#.*$", "").split("\\s+");
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
