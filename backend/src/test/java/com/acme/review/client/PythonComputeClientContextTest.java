package com.acme.review.client;

import com.acme.review.config.OrchestratorProperties;
import com.acme.review.config.PythonClientProperties;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class PythonComputeClientContextTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withBean(OrchestratorProperties.class, () -> new OrchestratorProperties(1, 1, 1, 60, 1000, 1000))
            .withBean(PythonClientProperties.class, () -> {
                PythonClientProperties properties = new PythonClientProperties();
                properties.setBaseUrl("http://localhost:8000");
                properties.setSyncPath("/ai/review/sync");
                properties.setDiscoveryEnabled(false);
                return properties;
            })
            .withUserConfiguration(PythonComputeClient.class);

    @Test
    void shouldStartWithoutRegistryWhenDiscoveryDisabled() {
        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).hasSingleBean(PythonComputeClient.class);
        });
    }
}
