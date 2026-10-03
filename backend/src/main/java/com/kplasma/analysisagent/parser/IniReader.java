package com.kplasma.analysisagent.parser;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/** Section-scoped INI reader. Only the known BiasPower.rfCycle U+0001 is accepted. */
public final class IniReader {
    private static final Pattern NUMBER = Pattern.compile("[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    private record Value(String text, int line) {}
    private final String path;
    private final Map<String, Value> values = new LinkedHashMap<>();

    public IniReader(String path, List<String> lines) {
        this.path = path;
        String section = "";
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i);
            int comment = line.indexOf('#');
            if (comment >= 0) {
                controls(line.substring(comment), path, i + 1, "comment", false);
                line = line.substring(0, comment);
            }
            int rawEquals = line.indexOf('=');
            if (rawEquals >= 0) {
                String rawKey = line.substring(0, rawEquals);
                String rawValue = line.substring(rawEquals + 1);
                controls(rawKey, path, i + 1, "INI", false);
                String field = section + "." + rawKey.strip();
                controls(rawValue, path, i + 1, field,
                        field.equals("BiasPower.rfCycle") && rawValue.matches("[ \t]*\u0001[ \t]*"));
            } else controls(line, path, i + 1, "INI", false);
            line = line.strip();
            if (line.isEmpty()) continue;
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.substring(1, line.length() - 1).strip();
                controls(section, path, i + 1, "section", false);
                continue;
            }
            int equals = line.indexOf('=');
            if (equals < 1 || section.isEmpty()) throw ParseFailure.malformed(path, i + 1, "INI", "Expected a section-scoped key=value");
            String key = line.substring(0, equals).strip();
            String text = line.substring(equals + 1).strip();
            String field = section + "." + key;
            controls(key, path, i + 1, field, false);
            controls(text, path, i + 1, field, field.equals("BiasPower.rfCycle") && text.equals("\u0001"));
            if (values.putIfAbsent(field, new Value(text, i + 1)) != null)
                throw ParseFailure.malformed(path, i + 1, field, "Duplicate INI field");
        }
    }
    public String text(String section, String key) { return required(section + "." + key).text(); }
    public double number(String section, String key) {
        String field = section + "." + key;
        var value = required(field);
        return finite(value.text(), path, value.line(), field);
    }
    public int line(String section, String key) { return required(section + "." + key).line(); }
    private Value required(String field) {
        var value = values.get(field);
        if (value == null || value.text().isEmpty()) throw ParseFailure.incomplete(path, field, "Required INI field is missing");
        return value;
    }
    public static double finite(String token, String path, int line, String field) {
        if (!NUMBER.matcher(token).matches()) throw ParseFailure.malformed(path, line, field, "Expected a finite numeric token");
        double value = Double.parseDouble(token);
        if (!Double.isFinite(value)) throw ParseFailure.malformed(path, line, field, "Nonfinite numeric value");
        return value;
    }
    static void controls(String text, String path, int line, String field, boolean knownRfCycle) {
        for (int i = 0; i < text.length(); i++) if (Character.isISOControl(text.charAt(i)) && text.charAt(i) != '\t'
                && !(knownRfCycle && text.charAt(i) == 1))
            throw ParseFailure.malformed(path, line, field, "Unexpected control character");
    }
}
