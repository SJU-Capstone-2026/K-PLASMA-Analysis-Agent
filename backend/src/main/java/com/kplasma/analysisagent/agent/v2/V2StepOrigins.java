package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.WorkspaceDto.TurnSnapshot;
import com.kplasma.analysisagent.contract.WorkspaceDto.V2RecordSource;

import java.util.List;
import java.util.Map;
import java.util.Objects;

public final class V2StepOrigins {
    private V2StepOrigins() {}

    public static boolean contains(TurnSnapshot turn, V2RecordSource source, RunRef ref) {
        if (turn == null || source == null || ref == null || !turn.id().equals(source.turnId())
            || source.executionId() == null || source.stepId() == null || source.groupId() == null
            || !"v2".equals(turn.answerSnapshot().get("implementationId"))
            || !(turn.answerSnapshot().get("stepResults") instanceof List<?> steps)) return false;
        for (Object raw : steps) {
            if (!(raw instanceof Map<?,?> step) || !Objects.equals(source.executionId(), step.get("executionId"))
                || !Objects.equals(source.stepId(), step.get("stepId"))) continue;
            return containsRef(group(step,source.groupId()),ref);
        }
        return false;
    }

    private static Object group(Map<?,?> step, String group) {
        if ("comparison".equals(group) && group.equals(step.get("groupId"))) return step.get("runRefs");
        if (!(step.get("outputs") instanceof Map<?,?> output)) return null;
        if ("common".equals(group) && group.equals(step.get("groupId"))) return output.get("candidates");
        if (!(output.get("toolResult") instanceof Map<?,?> result)) return null;
        if ("near".equals(group)) return result.get("nearMisses");
        if (group.startsWith("objective-") && result.get("objectiveResults") instanceof List<?> groups) {
            try {
                int index = Integer.parseInt(group.substring("objective-".length()));
                if (index >= 0 && index < groups.size() && groups.get(index) instanceof Map<?,?> item)
                    return item.get("candidateRefs");
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static boolean containsRef(Object values, RunRef ref) {
        if (!(values instanceof List<?> rows)) return false;
        for (Object value : rows) {
            if (!(value instanceof Map<?,?> row)) continue;
            Map<?,?> run = row.get("run") instanceof Map<?,?> nested ? nested : row;
            if (Objects.equals(ref.runId(),run.get("runId")) && Objects.equals(ref.runVersionId(),run.get("runVersionId")))
                return true;
        }
        return false;
    }
}
