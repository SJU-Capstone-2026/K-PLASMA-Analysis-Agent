package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.ingestion.IntakeException;

import java.util.List;
import java.util.Set;
import java.util.Arrays;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public final class GraphVersionPolicy {
    private static final Set<String> KNOWN = Set.of("v1", "v2", "v2_localLLM");
    private final List<String> supported;
    private final String defaultVersion;

    public GraphVersionPolicy(@Value("${kplasma.agent.supported-graph-versions:v1,v2}") String versions,
                              @Value("${kplasma.agent.default-graph-version:v1}") String defaultVersion) {
        this.supported = Arrays.stream(versions.split(",", -1)).map(String::trim).distinct().toList();
        if (!KNOWN.containsAll(supported) || !supported.contains(defaultVersion)) {
            throw new IllegalArgumentException("Invalid Agent graph deployment configuration");
        }
        this.defaultVersion = defaultVersion;
    }

    public static boolean isComposite(String version) {
        return "v2".equals(version) || "v2_localLLM".equals(version);
    }

    public boolean allowsLocal() { return supported.contains("v2_localLLM"); }
    public boolean localOnly() { return allowsLocal() && supported.size() == 1; }

    public String resolve(String pinned, String requested) {
        if ((requested != null && !supported.contains(requested)) || (pinned != null && !supported.contains(pinned))) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown graph version");
        }
        if (pinned != null && requested != null && !pinned.equals(requested)) {
            throw new IntakeException("GRAPH_VERSION_MISMATCH", 409, "Agent 버전을 바꾸려면 새 대화를 시작해 주세요.");
        }
        return pinned != null ? pinned : requested != null ? requested : defaultVersion;
    }

    public List<String> workerVersions(List<String> supplied) {
        if (supplied == null) supplied = List.of("v1");
        if (supplied.isEmpty() || supplied.stream().anyMatch(v -> v == null || !supported.contains(v))) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown or empty worker graph versions");
        }
        return supplied.stream().distinct().toList();
    }
}
