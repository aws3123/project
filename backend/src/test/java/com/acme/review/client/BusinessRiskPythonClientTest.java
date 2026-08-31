package com.acme.review.client;

import com.acme.review.config.PythonClientProperties;
import com.acme.review.dto.BusinessRiskPythonSourceRequest;
import com.acme.review.exception.PythonHttpException;
import com.acme.review.exception.PythonTimeoutException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.ExchangeFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.lang.reflect.Field;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class BusinessRiskPythonClientTest {

    private PythonClientProperties properties;

    @BeforeEach
    void setUp() {
        properties = new PythonClientProperties();
        properties.setTimeoutMs(500);
        properties.setBaseUrl("http://localhost:8000");
    }

    @Test
    void shouldRetryRetryableHttpErrorThenSucceed() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        ExchangeFunction exchange = request -> {
            if (attempts.getAndIncrement() == 0) {
                return Mono.just(ClientResponse.create(HttpStatus.TOO_MANY_REQUESTS)
                        .header("Content-Type", MediaType.TEXT_PLAIN_VALUE)
                        .body("retry")
                        .build());
            }
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                    .body("{\"taskId\":\"task-1\",\"status\":\"completed\"}")
                    .build());
        };

        BusinessRiskPythonClient client = buildClient(exchange);
        client.analyzeSource(request());

        assertThat(attempts.get()).isEqualTo(2);
    }

    @Test
    void shouldThrowTimeoutExceptionAfterRetryBudgetExhausted() throws Exception {
        ExchangeFunction exchange = request -> Mono.error(new TimeoutException("timeout"));

        BusinessRiskPythonClient client = buildClient(exchange);

        assertThatThrownBy(() -> client.analyzeSource(request()))
                .isInstanceOf(PythonTimeoutException.class)
                .hasMessageContaining("timed out");
    }

    @Test
    void shouldThrowNonRetryableHttpErrorImmediately() throws Exception {
        ExchangeFunction exchange = request -> Mono.just(ClientResponse.create(HttpStatus.BAD_REQUEST)
                .header("Content-Type", MediaType.TEXT_PLAIN_VALUE)
                .body("bad")
                .build());

        BusinessRiskPythonClient client = buildClient(exchange);

        assertThatThrownBy(() -> client.analyzeSource(request()))
                .isInstanceOf(PythonHttpException.class)
                .hasMessageContaining("400");
    }

    private BusinessRiskPythonClient buildClient(ExchangeFunction exchange) throws Exception {
        WebClient webClient = WebClient.builder().exchangeFunction(exchange).build();
        BusinessRiskPythonClient client = new BusinessRiskPythonClient(webClient, properties);
        setField(client, "pythonSourcePath", "/ai/business-risk/source");
        setField(client, "retryMaxAttempts", 2);
        setField(client, "retryBackoffMs", 0L);
        return client;
    }

    private BusinessRiskPythonSourceRequest request() {
        BusinessRiskPythonSourceRequest request = new BusinessRiskPythonSourceRequest();
        request.setTaskId("task-1");
        request.setTraceId("trace-1");
        return request;
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
