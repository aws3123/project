package com.acme.review.health;

import com.acme.review.config.PythonClientProperties;
import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.acme.review.service.BusinessRiskMetricsService;
import com.acme.review.service.BusinessRiskWorkerRegistryService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.actuate.health.Health;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.ExchangeFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class PythonHealthIndicatorTest {

    private static final String HEALTH_PATH = "/ai/health/business-risk-source";

    private PythonClientProperties properties;
    private BusinessRiskWorkerRegistryService workerRegistryService;
    private BusinessRiskMetricsService metricsService;

    @BeforeEach
    void setUp() {
        properties = new PythonClientProperties();
        properties.setBaseUrl("http://localhost:8000");
        properties.setTimeoutMs(500);
        properties.setBusinessRiskHealthPath(HEALTH_PATH);
        workerRegistryService = mock(BusinessRiskWorkerRegistryService.class);
        metricsService = new BusinessRiskMetricsService(new SimpleMeterRegistry());
    }

    @Test
    void shouldReportUpWhenBusinessRiskReadinessIsUp() {
        properties.setDiscoveryEnabled(false);
        PythonHealthIndicator indicator = buildIndicator(request -> Mono.just(ClientResponse.create(HttpStatus.OK)
                .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                .body("{\"overall\":\"UP\"}")
                .build()));

        Health health = indicator.health();

        assertThat(health.getStatus().getCode()).isEqualTo("UP");
        assertThat(health.getDetails()).containsEntry("path", HEALTH_PATH);
    }

    @Test
    void shouldReportDownReasonWhenBusinessRiskReadinessIsDown() {
        properties.setDiscoveryEnabled(false);
        PythonHealthIndicator indicator = buildIndicator(request -> Mono.just(ClientResponse.create(HttpStatus.SERVICE_UNAVAILABLE)
                .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                .body("{\"overall\":\"DOWN\",\"config\":{\"detail\":\"llm_api_key is required\"}}")
                .build()));

        Health health = indicator.health();

        assertThat(health.getStatus().getCode()).isEqualTo("DOWN");
        assertThat(health.getDetails()).containsEntry("reason", "llm_api_key is required");
    }

    @Test
    void shouldReportDownWhenDiscoveryIsEnabledAndNoWorkerIsReady() {
        properties.setDiscoveryEnabled(true);
        when(workerRegistryService.snapshot()).thenReturn(blockedSnapshot("PYTHON_WORKER_UNAVAILABLE"));
        PythonHealthIndicator indicator = buildIndicator(request -> Mono.error(new IllegalStateException("should not call http fallback")));

        Health health = indicator.health();

        assertThat(health.getStatus().getCode()).isEqualTo("DOWN");
        assertThat(health.getDetails()).containsEntry("reason", "PYTHON_WORKER_UNAVAILABLE");
    }

    @Test
    void shouldReportUpWhenDiscoveryIsEnabledAndWorkerIsReady() {
        properties.setDiscoveryEnabled(true);
        when(workerRegistryService.snapshot()).thenReturn(allowedSnapshot());
        PythonHealthIndicator indicator = buildIndicator(request -> Mono.error(new IllegalStateException("should not call http fallback")));

        Health health = indicator.health();

        assertThat(health.getStatus().getCode()).isEqualTo("UP");
        assertThat(health.getDetails()).containsEntry("readyWorkers", 1);
    }

    private PythonHealthIndicator buildIndicator(ExchangeFunction exchange) {
        WebClient webClient = WebClient.builder().exchangeFunction(exchange).build();
        return new PythonHealthIndicator(webClient, properties, workerRegistryService, metricsService);
    }

    private BusinessRiskWorkerRegistrySnapshot allowedSnapshot() {
        BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();
        snapshot.setActiveWorkers(1);
        snapshot.setReadyWorkers(1);
        snapshot.setAvailableSlots(2);
        snapshot.setDispatchAllowed(true);
        return snapshot;
    }

    private BusinessRiskWorkerRegistrySnapshot blockedSnapshot(String reason) {
        BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();
        snapshot.setActiveWorkers(0);
        snapshot.setReadyWorkers(0);
        snapshot.setAvailableSlots(0);
        snapshot.setDispatchAllowed(false);
        snapshot.setBlockReason(reason);
        return snapshot;
    }
}
