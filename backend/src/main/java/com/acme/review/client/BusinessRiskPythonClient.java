package com.acme.review.client;

import com.acme.review.config.PythonClientProperties;
import com.acme.review.dto.BusinessRiskPythonSourceRequest;
import com.acme.review.dto.BusinessRiskPythonSourceResponse;
import com.acme.review.exception.PythonHttpException;
import com.acme.review.exception.PythonServiceException;
import com.acme.review.exception.PythonTimeoutException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;

@Slf4j
@Component
@RequiredArgsConstructor
public class BusinessRiskPythonClient {

    private final WebClient pythonWebClient;
    private final PythonClientProperties pythonClientProperties;

    @Value("${business-risk.source.python-path:/ai/business-risk/source}")
    private String pythonSourcePath;

    @Value("${business-risk.source.retry.max-attempts:3}")
    private int retryMaxAttempts;

    @Value("${business-risk.source.retry.backoff-ms:300}")
    private long retryBackoffMs;

    public BusinessRiskPythonSourceResponse analyzeSource(BusinessRiskPythonSourceRequest request) {
        int attempts = Math.max(1, retryMaxAttempts);
        PythonServiceException lastFailure = null;

        for (int attempt = 1; attempt <= attempts; attempt++) {
            try {
                return analyzeSourceOnce(request);
            } catch (PythonHttpException ex) {
                if (!ex.isRetryable() || attempt == attempts) {
                    throw ex;
                }
                lastFailure = ex;
                log.warn("Retryable Python HTTP error taskId={} status={} attempt={}/{}",
                        request.getTaskId(), ex.getStatusCode(), attempt, attempts);
            } catch (PythonTimeoutException ex) {
                if (attempt == attempts) {
                    throw ex;
                }
                lastFailure = new PythonServiceException(ex.getMessage(), ex);
                log.warn("Python timeout taskId={} attempt={}/{}", request.getTaskId(), attempt, attempts);
            } catch (PythonServiceException ex) {
                if (attempt == attempts) {
                    throw ex;
                }
                lastFailure = ex;
                log.warn("Python transport error taskId={} attempt={}/{}", request.getTaskId(), attempt, attempts);
            }

            sleepBackoff(attempt);
        }

        throw new PythonServiceException("Python business risk source exhausted retry budget", lastFailure);
    }

    private BusinessRiskPythonSourceResponse analyzeSourceOnce(BusinessRiskPythonSourceRequest request) {
        long timeoutMs = pythonClientProperties.getTimeoutMs();
        try {
            log.info("Calling Python business risk source taskId={} path={} timeoutMs={}",
                    request.getTaskId(), pythonSourcePath, timeoutMs);
            return pythonWebClient.post()
                    .uri(pythonSourcePath)
                    .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .header("X-Trace-Id", request.getTraceId() != null ? request.getTraceId() : "")
                    .bodyValue(request)
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(),
                            response -> response.bodyToMono(String.class)
                                    .defaultIfEmpty("<empty>")
                                    .flatMap(body -> {
                                        int statusCode = response.statusCode().value();
                                        boolean retryable = statusCode >= 500 || statusCode == 429 || statusCode == 408;
                                        return Mono.error(new PythonHttpException(
                                                "Python business risk source error: " + statusCode + " body=" + body,
                                                statusCode,
                                                retryable
                                        ));
                                    }))
                    .bodyToMono(BusinessRiskPythonSourceResponse.class)
                    .timeout(Duration.ofMillis(timeoutMs))
                    .block(Duration.ofMillis(timeoutMs + 1000));
        } catch (PythonHttpException ex) {
            throw ex;
        } catch (Exception ex) {
            if (isTimeout(ex)) {
                throw new PythonTimeoutException("Python business risk source timed out after " + timeoutMs + "ms", ex);
            }

            Throwable cause = rootCause(ex);
            if (cause instanceof PythonHttpException httpException) {
                throw httpException;
            }
            if (cause instanceof PythonServiceException serviceException) {
                throw serviceException;
            }
            throw new PythonServiceException("Failed to call Python business risk source", ex);
        }
    }

    private void sleepBackoff(int attempt) {
        long delayMs = Math.max(0L, retryBackoffMs * attempt);
        if (delayMs == 0L) {
            return;
        }
        try {
            Thread.sleep(delayMs);
        } catch (InterruptedException interruptedException) {
            Thread.currentThread().interrupt();
            throw new PythonServiceException("Python retry interrupted", interruptedException);
        }
    }

    private boolean isTimeout(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            String message = current.getMessage();
            if ((message != null && (message.contains("timeout") || message.contains("Timeout")))
                    || current instanceof java.util.concurrent.TimeoutException) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }

    private Throwable rootCause(Throwable throwable) {
        Throwable current = throwable;
        while (current.getCause() != null && current.getCause() != current) {
            current = current.getCause();
        }
        return current;
    }
}
