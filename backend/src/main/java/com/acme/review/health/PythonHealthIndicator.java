package com.acme.review.health;

import com.acme.review.config.PythonClientProperties;
import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.acme.review.service.BusinessRiskMetricsService;
import com.acme.review.service.BusinessRiskWorkerRegistryService;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.Map;

@Component("python")
@RequiredArgsConstructor
public class PythonHealthIndicator implements HealthIndicator {

    private static final String DEFAULT_DOWN_REASON = "business risk readiness reported DOWN";

    private final WebClient pythonWebClient;
    private final PythonClientProperties pythonClientProperties;
    private final BusinessRiskWorkerRegistryService workerRegistryService;
    private final BusinessRiskMetricsService metricsService;

    @SuppressWarnings("unchecked")
    @Override
    public Health health() {
        if (pythonClientProperties.isDiscoveryEnabled()) {
            BusinessRiskWorkerRegistrySnapshot snapshot = workerRegistryService.snapshot();
            metricsService.recordWorkerSnapshot(snapshot);
            if (snapshot.isDispatchAllowed()) {
                return Health.up()
                        .withDetail("activeWorkers", snapshot.getActiveWorkers())
                        .withDetail("readyWorkers", snapshot.getReadyWorkers())
                        .withDetail("availableSlots", snapshot.getAvailableSlots())
                        .withDetail("staleWorkers", snapshot.getStaleWorkers())
                        .build();
            }
            return Health.down()
                    .withDetail("activeWorkers", snapshot.getActiveWorkers())
                    .withDetail("readyWorkers", snapshot.getReadyWorkers())
                    .withDetail("availableSlots", snapshot.getAvailableSlots())
                    .withDetail("staleWorkers", snapshot.getStaleWorkers())
                    .withDetail("reason", snapshot.getBlockReason())
                    .build();
        }

        String path = pythonClientProperties.getBusinessRiskHealthPath();
        try {
            Health health = pythonWebClient.get()
                    .uri(path)
                    .exchangeToMono(response -> response.bodyToMono(Map.class)
                            .defaultIfEmpty(Map.of())
                            .map(payload -> buildHealth(path, payload)))
                    .block(Duration.ofMillis(Math.max(1000, pythonClientProperties.getTimeoutMs())));

            return health != null
                    ? health
                    : Health.down()
                    .withDetail("baseUrl", pythonClientProperties.getBaseUrl())
                    .withDetail("path", path)
                    .withDetail("reason", DEFAULT_DOWN_REASON)
                    .build();
        } catch (Exception ex) {
            return Health.down(ex)
                    .withDetail("baseUrl", pythonClientProperties.getBaseUrl())
                    .withDetail("path", path)
                    .build();
        }
    }

    private Health buildHealth(String path, Map<String, Object> payload) {
        if (isUp(payload)) {
            return Health.up()
                    .withDetail("baseUrl", pythonClientProperties.getBaseUrl())
                    .withDetail("path", path)
                    .build();
        }

        return Health.down()
                .withDetail("baseUrl", pythonClientProperties.getBaseUrl())
                .withDetail("path", path)
                .withDetail("reason", extractReason(payload))
                .build();
    }

    private boolean isUp(Map<String, Object> payload) {
        return payload != null && "UP".equalsIgnoreCase(String.valueOf(payload.get("overall")));
    }

    private String extractReason(Map<String, Object> payload) {
        String configDetail = extractNestedDetail(payload, "config");
        if (configDetail != null) {
            return configDetail;
        }

        String llmDetail = extractNestedDetail(payload, "llm");
        if (llmDetail != null) {
            return llmDetail;
        }

        return DEFAULT_DOWN_REASON;
    }

    private String extractNestedDetail(Map<String, Object> payload, String key) {
        if (payload == null) {
            return null;
        }

        Object nested = payload.get(key);
        if (!(nested instanceof Map<?, ?> nestedMap)) {
            return null;
        }

        Object detail = nestedMap.get("detail");
        if (detail == null) {
            return null;
        }

        String value = String.valueOf(detail).trim();
        return value.isEmpty() ? null : value;
    }
}
