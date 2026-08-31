package com.acme.review.client;

import com.acme.review.config.OrchestratorProperties;
import com.acme.review.config.PythonClientProperties;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.ExchangeFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.HttpStatus.NOT_FOUND;
import static org.springframework.http.HttpStatus.OK;

class PythonComputeClientFetchLogsTest {

    @Test
    void shouldReturnEmptyLogsWhenPythonReturnsNotFound() throws Exception {
        PythonComputeClient client = buildClient(request -> Mono.just(ClientResponse.create(NOT_FOUND)
                .header("Content-Type", TEXT_PLAIN_VALUE)
                .body("Logs not found")
                .build()));

        assertThat(client.fetchLogs("task-404")).isEmpty();
    }

    @Test
    void shouldReturnLogsWhenPythonReturnsPayload() throws Exception {
        PythonComputeClient client = buildClient(request -> Mono.just(ClientResponse.create(OK)
                .header("Content-Type", APPLICATION_JSON_VALUE)
                .body("[{\"node\":\"verify_business_risks\",\"status\":\"SUCCESS\",\"timestamp\":\"2026-05-30T00:00:00Z\"}]")
                .build()));

        List<Map<String, Object>> logs = client.fetchLogs("task-1");

        assertThat(logs).hasSize(1);
        assertThat(logs.get(0)).containsEntry("node", "verify_business_risks");
    }

    private PythonComputeClient buildClient(ExchangeFunction exchange) throws Exception {
        PythonClientProperties properties = new PythonClientProperties();
        properties.setBaseUrl("http://localhost:8000");
        properties.setSyncPath("/ai/review/sync");
        properties.setLogsPath("/ai/review/logs");
        properties.setDiscoveryEnabled(false);
        properties.setConnectTimeoutMs(1000);

        PythonComputeClient client = new PythonComputeClient(properties, new OrchestratorProperties(1, 1, 1, 60, 1000, 1000));
        WebClient webClient = WebClient.builder().exchangeFunction(exchange).build();
        setField(client, "defaultWebClient", webClient);
        return client;
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private static final String TEXT_PLAIN_VALUE = "text/plain";
    private static final String APPLICATION_JSON_VALUE = "application/json";
}
