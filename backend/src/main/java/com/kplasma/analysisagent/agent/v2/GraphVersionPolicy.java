package com.kplasma.analysisagent.agent.v2;

import com.kplasma.analysisagent.ingestion.IntakeException;

import java.util.List;
import java.util.Set;
import java.util.Arrays;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public final class GraphVersionPolicy {
    private static final Set<String> RETIRED = Set.of("v1", "v3");
    private final List<String> supported;
    private final String defaultVersion;

    public GraphVersionPolicy(@Value("${kplasma.agent.supported-graph-versions:v2}") String versions,
                              @Value("${kplasma.agent.default-graph-version:v2}") String defaultVersion) {
        var configured = Arrays.stream(versions.split(",", -1)).map(String::trim).distinct().toList();
        this.supported = configured.stream().filter(GraphVersionPolicy::isComposite).toList();
        this.defaultVersion = RETIRED.contains(defaultVersion) ? "v2" : defaultVersion;
        if (configured.stream().anyMatch(version -> !isComposite(version) && !RETIRED.contains(version))
                || !supported.contains(this.defaultVersion)) {
            throw new IllegalArgumentException("Invalid Agent graph deployment configuration");
        }
    }

    public static boolean isComposite(String version) {
        return "v2".equals(version) || "v2_localLLM".equals(version);
    }

    public boolean allowsLocal() { return supported.contains("v2_localLLM"); }
    public boolean localOnly() { return allowsLocal() && supported.size() == 1; }

    public String resolve(String pinned, String requested) {
        if (pinned != null && RETIRED.contains(pinned)) {
            throw new IntakeException("GRAPH_VERSION_RETIRED", 409, "이전 버전의 대화는 조회할 수 있습니다. 새 대화를 시작해 주세요.");
        }
        if ((requested != null && !supported.contains(requested)) || (pinned != null && !supported.contains(pinned))) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown graph version");
        }
        if (pinned != null && requested != null && !pinned.equals(requested)) {
            throw new IntakeException("GRAPH_VERSION_MISMATCH", 409, "Agent 버전을 바꾸려면 새 대화를 시작해 주세요.");
        }
        return pinned != null ? pinned : requested != null ? requested : defaultVersion;
    }

    public List<String> workerVersions(List<String> supplied) {
        if (supplied == null || supplied.isEmpty() || supplied.stream().anyMatch(v -> v == null || !supported.contains(v))) {
            throw new IntakeException("INVALID_AGENT_REQUEST", 400, "Unknown or empty worker graph versions");
        }
        return supplied.stream().distinct().toList();
    }
}
