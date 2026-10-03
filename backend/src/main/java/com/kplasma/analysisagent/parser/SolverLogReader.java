package com.kplasma.analysisagent.parser;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/** Solver labels and species are scoped to the exact bracketed section. */
public final class SolverLogReader {
    private record Row(String text, int line) {}
    private final String path;
    private final Map<String, List<Row>> sections = new LinkedHashMap<>();
    private final List<Row> preamble = new ArrayList<>();
    public SolverLogReader(String path, List<String> lines) {
        this.path = path;
        List<Row> rows = preamble;
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i).strip();
            // '#' within (#/cm^3) is a unit symbol, not a comment.
            line = line.replaceFirst("\\s+#.*$", "").strip();
            IniReader.controls(line, path, i + 1, "solver", false);
            if (line.startsWith("[") && line.endsWith("]")) {
                String section = line.substring(1, line.length() - 1);
                rows = new ArrayList<>();
                if (sections.putIfAbsent(section, rows) != null)
                    throw ParseFailure.malformed(path, i + 1, section, "Duplicate solver section");
            } else if (!line.isEmpty()) rows.add(new Row(line, i + 1));
        }
    }
    public void requireRelease() {
        List<Row> releases = preamble.stream().filter(r -> r.text().startsWith("RELEASE ")).toList();
        if (releases.size() != 1 || !releases.getFirst().text().matches("RELEASE\\s+8\\.8\\.1(?:,.*)?"))
            throw ParseFailure.malformed(path, releases.isEmpty() ? 0 : releases.getFirst().line(), "RELEASE", "Unsupported solver release");
    }
    public boolean hasSection(String section) { return sections.containsKey(section); }
    public String text(String section, String label) { return assignment(section, label).text(); }
    public double number(String section, String label, String unit) {
        var row = assignment(section, label);
        var match = Pattern.compile("(.+?)\\s+\\(" + Pattern.quote(unit) + "\\)").matcher(row.text());
        if (!match.matches()) throw ParseFailure.malformed(path, row.line(), section + "." + label, "Wrong scalar unit or syntax");
        return IniReader.finite(match.group(1), path, row.line(), section + "." + label);
    }
    public double species(String section, String species, String unit) {
        List<Row> rows = section(section);
        if (rows.stream().noneMatch(r -> r.text().matches("Species\\s+\\(" + Pattern.quote(unit) + "\\)")))
            throw ParseFailure.malformed(path, rows.isEmpty() ? 0 : rows.getFirst().line(), section, "Missing or incompatible species unit heading");
        var pattern = Pattern.compile(Pattern.quote(species) + "\\s+(.+)");
        Row found = null;
        for (var row : rows) {
            var match = pattern.matcher(row.text());
            if (match.matches()) {
                if (found != null) throw ParseFailure.malformed(path, row.line(), section + "." + species, "Duplicate species row");
                found = new Row(match.group(1), row.line());
            } else if (row.text().equals(species)) throw ParseFailure.malformed(path, row.line(), section + "." + species, "Missing species value");
        }
        if (found == null) throw ParseFailure.incomplete(path, section + "." + species, "Required species row is missing");
        return IniReader.finite(found.text(), path, found.line(), section + "." + species);
    }
    private Row assignment(String section, String label) {
        var pattern = Pattern.compile(Pattern.quote(label) + "\\s*=\\s*(.*)");
        Row found = null;
        for (var row : section(section)) {
            var match = pattern.matcher(row.text());
            if (match.matches()) {
                if (found != null) throw ParseFailure.malformed(path, row.line(), section + "." + label, "Duplicate solver field");
                found = new Row(match.group(1).strip(), row.line());
            }
        }
        if (found == null) throw ParseFailure.incomplete(path, section + "." + label, "Required solver field is missing");
        return found;
    }
    private List<Row> section(String section) {
        var rows = sections.get(section);
        if (rows == null) throw ParseFailure.incomplete(path, section, "Required solver section is missing");
        return rows;
    }
}
