package com.kplasma.analysisagent.parser;

/** Safe Run-relative diagnostics, never storage paths or raw source contents. */
public final class ParseFailure extends RuntimeException {
    private final String status;
    private final String path;
    private final int line;
    private final String field;
    public ParseFailure(String status, String path, int line, String field, String reason) {
        super(reason);
        if (!status.equals("INCOMPLETE") && !status.equals("PARSE_FAILED")) throw new IllegalArgumentException("Invalid parse failure status");
        this.status = status; this.path = path; this.line = line; this.field = field;
    }
    public String status() { return status; }
    public String path() { return path; }
    public int line() { return line; }
    public String field() { return field; }
    public static ParseFailure incomplete(String path, String field, String reason) {
        return new ParseFailure("INCOMPLETE", path, 0, field, reason);
    }
    public static ParseFailure malformed(String path, int line, String field, String reason) {
        return new ParseFailure("PARSE_FAILED", path, line, field, reason);
    }
}
