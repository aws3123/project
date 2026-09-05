package com.acme.review.client;

import com.acme.review.config.OrchestratorProperties;
import com.acme.review.config.PythonClientProperties;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.exception.PythonServiceException;
import com.acme.review.exception.PythonTimeoutException;
import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.netty.channel.ChannelOption;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Slf4j
@Component
public class PythonComputeClient {

    private static final String TRACE_ID_KEY = "traceId";

    /**
     * 流式调用空闲超时：任意相邻 SSE 信号（含心跳）之间的最大间隔。
     * Python 侧心跳间隔 15s，这里取 4 倍余量。
     */
    private static final long STREAM_IDLE_TIMEOUT_MS = 60_000L;

    private final WebClient defaultWebClient;
    private final PythonClientProperties pyProps;
    private final OrchestratorProperties orchProps;
    private final ConcurrentHashMap<String, WebClient> webClientCache = new ConcurrentHashMap<>();

    @Autowired(required = false)
    private PythonServiceRegistry registry;

    public PythonComputeClient(PythonClientProperties pyProps,
                               OrchestratorProperties orchProps) {
        this.pyProps = pyProps;
        this.orchProps = orchProps;

        this.defaultWebClient = buildWebClient(pyProps.getBaseUrl());
    }

    private WebClient buildWebClient(String baseUrl) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, pyProps.getConnectTimeoutMs() > 0
                        ? (int) pyProps.getConnectTimeoutMs() : 3000)
                .responseTimeout(Duration.ofMillis(orchProps.asyncTimeoutMs()));

        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .baseUrl(baseUrl)
                .build();
    }

    private WebClient resolveWebClient() {
        if (!pyProps.isDiscoveryEnabled() || registry == null) {
            return defaultWebClient;
        }
        String instanceUrl = registry.getNextInstance();
        return webClientCache.computeIfAbsent(instanceUrl, this::buildWebClient);
    }

    private WebClient resolveWebClientForFetch() {
        if (!pyProps.isDiscoveryEnabled() || registry == null) {
            return defaultWebClient;
        }
        List<String> instances = registry.getAvailableInstances();
        if (instances.isEmpty()) {
            return defaultWebClient;
        }
        String instanceUrl = instances.get(0);
        return webClientCache.computeIfAbsent(instanceUrl, this::buildWebClient);
    }

    @CircuitBreaker(name = "pythonService", fallbackMethod = "fallbackCompute")
    public ReviewSyncResponse computeSync(ReviewSyncRequest request) {
        return compute(request, orchProps.syncTimeoutMs());
    }

    /**
     * 流式同步审查：订阅 Python 的 SSE 事件流，全程不阻塞调用线程。
     *
     * 保护层级：
     * 1. 连接超时：buildWebClient 中的 CONNECT_TIMEOUT_MILLIS（默认 3s）
     * 2. 空闲超时：Flux.timeout(60s)——Python 侧每 15s 发心跳，
     *    60s 无任何信号意味着 Python 进程死亡或网络中断
     * 3. 总预算：由调用方（SyncStrategy）按 sync-timeout-ms 检查
     *
     * 事件转发：所有事件（含 heartbeat）原样上抛，由调用方决定转发策略。
     */
    public Flux<ServerSentEvent<String>> computeSyncStream(ReviewSyncRequest request) {
        String traceId = MDC.get(TRACE_ID_KEY);
        WebClient client = resolveWebClient();
        log.info("Calling Python compute stream taskId={}", request.getTaskId());
        return client.post()
                .uri(pyProps.getSyncPath() + "/stream")
                .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .header("X-Trace-Id", traceId != null ? traceId : "")
                .bodyValue(request)
                .retrieve()
                .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(),
                        response -> response.bodyToMono(String.class)
                                .defaultIfEmpty("<empty>")
                                .flatMap(body -> Mono.error(
                                        new PythonServiceException("Python service error: " + response.statusCode() + " body=" + body))))
                .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
                .timeout(Duration.ofMillis(STREAM_IDLE_TIMEOUT_MS));
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> fetchLogs(String taskId) {
        String traceId = MDC.get(TRACE_ID_KEY);
        log.info("Fetching logs from Python taskId={}", taskId);
        try {
            WebClient client = resolveWebClientForFetch();
            String path = (pyProps.getLogsPath() != null ? pyProps.getLogsPath() : "/ai/review/logs") + "/" + taskId;
            List<Map<String, Object>> logs = client.get()
                    .uri(path)
                    .header("X-Trace-Id", traceId != null ? traceId : "")
                    .retrieve()
                    .bodyToMono(List.class)
                    .timeout(Duration.ofMillis(5000))
                    .block(Duration.ofMillis(6000));
            return logs != null ? logs : List.of();
        } catch (WebClientResponseException.NotFound e) {
            log.info("Python logs not found taskId={}", taskId);
            return List.of();
        } catch (Exception e) {
            log.warn("Failed to fetch logs from Python taskId={}", taskId, e);
            return List.of();
        }
    }

    /**
     * 熔断降级方法（同步），CB 开启或抛出异常时返回快速失败响应。
     */
    @SuppressWarnings("unused")
    private ReviewSyncResponse fallbackCompute(ReviewSyncRequest request, Throwable t) {
        log.warn("Circuit breaker fallback for Python compute taskId={} reason={}: {}",
                request.getTaskId(), t.getClass().getSimpleName(), t.getMessage());
        if (t instanceof CallNotPermittedException) {
            throw new PythonServiceException("Python service is temporarily unavailable (circuit open), taskId=" + request.getTaskId());
        }
        if (t instanceof PythonTimeoutException || t instanceof PythonServiceException) {
            throw (RuntimeException) t;
        }
        throw new PythonServiceException("Python compute failed after circuit breaker, taskId=" + request.getTaskId(), t);
    }

    private ReviewSyncResponse compute(ReviewSyncRequest request, long timeoutMs) {
        String traceId = MDC.get(TRACE_ID_KEY);
        WebClient client = resolveWebClient();

        try {
            log.info("Calling Python compute taskId={} timeoutMs={}", request.getTaskId(), timeoutMs);
            return client.post()
                    .uri(pyProps.getSyncPath())
                    .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .header("X-Trace-Id", traceId != null ? traceId : "")
                    .bodyValue(request)
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(),
                            response -> response.bodyToMono(String.class)
                                    .defaultIfEmpty("<empty>")
                                    .flatMap(body -> reactor.core.publisher.Mono.error(
                                            new PythonServiceException("Python service error: " + response.statusCode() + " body=" + body))))
                    .bodyToMono(ReviewSyncResponse.class)
                    .timeout(Duration.ofMillis(timeoutMs))
                    .block(Duration.ofMillis(timeoutMs + 1000));
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : "";
            Throwable cause = e.getCause();
            if (msg.contains("timeout") || msg.contains("Timeout") ||
                    (cause != null && cause.getMessage() != null &&
                            (cause.getMessage().contains("timeout") || cause.getMessage().contains("Timeout")))) {
                log.error("Python compute timeout taskId={} timeoutMs={}", request.getTaskId(), timeoutMs);
                throw new PythonTimeoutException("Python compute timed out after " + timeoutMs + "ms", e);
            }
            if (cause instanceof PythonServiceException) {
                throw (PythonServiceException) cause;
            }
            log.error("Python compute failed taskId={}", request.getTaskId(), e);
            throw new PythonServiceException("Failed to call Python service", e);
        }
    }
}
