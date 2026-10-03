package com.kplasma.analysisagent.contract;

import java.util.List;

public final class RunDeletionDto {
    private RunDeletionDto() {}
    // Keep JSON values uncoerced until validation: a numeric id is not a string id.
    public record Request(List<?> runIds) {}
    public record Result(List<String> deletedRunIds, boolean cleanupPending) {}
}
