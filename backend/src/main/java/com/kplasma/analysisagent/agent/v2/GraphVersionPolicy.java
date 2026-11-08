package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.ingestion.IntakeException;

import java.util.List;
import java.util.Set;

public final class GraphVersionPolicy {
    private static final Set<String> SUPPORTED = Set.of("v1", "v2");
    private GraphVersionPolicy() {}

    public static String resolve(String pinned, String requested) {
        if (requested != null && !SUPPORTED.contains(requested)) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown graph version");
        }
        if (pinned != null && requested != null && !pinned.equals(requested)) {
            throw new IntakeException("GRAPH_VERSION_MISMATCH", 409, "Agent 버전을 바꾸려면 새 대화를 시작해 주세요.");
        }
        return pinned != null ? pinned : requested != null ? requested : "v1";
    }

    public static List<String> workerVersions(List<String> supplied) {
        if (supplied == null) return List.of("v1");
        if (supplied.isEmpty() || supplied.stream().anyMatch(v -> v == null || !SUPPORTED.contains(v))) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown or empty worker graph versions");
        }
        return supplied.stream().distinct().toList();
    }
}
