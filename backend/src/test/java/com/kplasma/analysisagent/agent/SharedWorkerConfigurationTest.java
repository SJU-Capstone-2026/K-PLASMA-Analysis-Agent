package com.kplasma.analysisagent.agent;

import com.kplasma.analysisagent.agent.v2.GraphVersionPolicy;
import com.kplasma.analysisagent.run.RunOutputService;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class SharedWorkerConfigurationTest {
    private final ApplicationContextRunner context = new ApplicationContextRunner()
        .withUserConfiguration(GraphVersionPolicy.class, AgentWorkerController.class)
        .withBean(AgentRequestService.class, () -> mock(AgentRequestService.class))
        .withBean(RunOutputService.class, () -> mock(RunOutputService.class));

    @Test void mixedDeploymentRequiresDistinctWorkerKeys() {
        for (String local : new String[]{"", "synthetic-cloud"}) {
            context.withPropertyValues("kplasma.agent.supported-graph-versions=v1,v2,v2_localLLM",
                "kplasma.agent.default-graph-version=v2", "kplasma.agent.worker-token=synthetic-cloud",
                "kplasma.agent.local-worker-token=" + local)
                .run(c -> assertThat(c).hasFailed());
        }
        context.withPropertyValues("kplasma.agent.supported-graph-versions=v1,v2,v2_localLLM",
            "kplasma.agent.default-graph-version=v2", "kplasma.agent.worker-token=synthetic-cloud",
            "kplasma.agent.local-worker-token=synthetic-local")
            .run(c -> assertThat(c).hasNotFailed());
    }

    @Test void existingSingleRuntimeConfigurationsKeepTheirOriginalKey() {
        for (String versions : new String[]{"v1,v2", "v2_localLLM"}) {
            context.withPropertyValues("kplasma.agent.supported-graph-versions=" + versions,
                "kplasma.agent.default-graph-version=" + versions.split(",")[0],
                "kplasma.agent.worker-token=synthetic-existing")
                .run(c -> assertThat(c).hasNotFailed());
        }
    }
}
