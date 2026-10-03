package com.kplasma.analysisagent.ingestion;
public class IntakeException extends RuntimeException {
    private final String code;
    private final int status;
    public IntakeException(String code, int status, String message) { super(message); this.code = code; this.status = status; }
    public String code() { return code; }
    public int status() { return status; }
    static IntakeException invalid(String message) { return new IntakeException("INVALID_UPLOAD", 400, message); }
    static IntakeException limit(String message) { return new IntakeException("UPLOAD_LIMIT_EXCEEDED", 413, message); }
}
