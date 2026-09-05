package com.acme.review.service.strategy;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.dto.ReviewStreamErrorEvent;
import com.acme.review.dto.ReviewStreamFinishedEvent;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.exception.PythonServiceException;
import com.acme.review.exception.PythonTimeoutException;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.ReviewStreamEventStore;
import com.acme.review.service.SseRegistry;
import com.acme.review.util.MarkdownImageProcessor;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 同步审核执行策略。
 *
 * 提供两种执行方式：
 * 1. executeSync：阻塞式（旧路径，保留作为回滚通道）
 * 2. executeSyncStream：流式（新路径，业内主流端到端 SSE）——
 *    Java 不再 block 等待完整结果，而是订阅 Python 的 SSE 事件流并
 *    逐事件转发给前端；终态事件（run_finished/run_error）触发落库。
 */
@Slf4j
@Component("syncReviewStrategy")
public class SyncStrategy extends AbstractReviewExecutionStrategy {

    /** 流式 SseEmitter 超时：需大于 orchestrator.sync-timeout-ms 总预算，作兜底。 */
    private static final long STREAM_EMITTER_TIMEOUT_MS = 180_000L;

    private final ObjectMapper objectMapper;
    private final ReviewStreamEventStore eventStore;

    public SyncStrategy(ReviewTaskMapper taskRepo,
                        ReviewResultMapper resultRepo,
                        PythonComputeClient pythonClient,
                        ConcurrentMetricsService metrics,
                        SseRegistry sseRegistry,
                        OrchestratorProperties orchProps,
                        TaskAuditLogMapper auditLogMapper,
                        ObjectMapper objectMapper,
                        ReviewStreamEventStore eventStore) {
        super(taskRepo, resultRepo, pythonClient, metrics, sseRegistry, orchProps, auditLogMapper);
        this.objectMapper = objectMapper;
        this.eventStore = eventStore;
    }

    @Transactional(rollbackFor = Exception.class)
    public ReviewSyncResponse executeSync(ReviewSyncRequest request) {
        metrics.recordSubmit();
        metrics.recordSync();

        String taskId = resolveOrGenerateTaskId(request);
        request.setTaskId(taskId);

        ReviewTask task = ReviewTask.fromRequest(taskId, request);
        task.setStatus(ReviewTaskStatus.PROCESSING);
        task.setTraceId(resolveTraceId());
        taskRepo.saveOrUpdate(task);

        log.info("Executing sync review taskId={}", taskId);

        return executePythonCall(request, task,
                () -> pythonClient.computeSync(request),
                (response, latency) -> {
                    metrics.recordSyncLatency(latency);
                    return ReviewTaskStatus.SUCCESS;
                });
    }

    /**
     * 流式同步审核：立即返回 SseEmitter，审查进度逐事件推送给前端。
     *
     * 生命周期：
     * - 进度事件（run_started/step_started/step_finished/heartbeat）原样转发
     * - run_finished → 图片 URL 后处理 → 落库 SUCCESS → 转发处理后结果 → 结束流
     * - run_error / 流异常 / 空闲超时 / 总预算超时 → 落库 FAILED → 推送错误 → 结束流
     *
     * 注意：前端断开（emitter 发送失败）不取消 Python 订阅——
     * 继续消费到终态完成落库，用户仍可通过任务查询拿到结果。
     *
     * 刻意不加 @Transactional：SSE 是长生命周期操作，事务不能横跨整个
     * 流式过程（会长时间占用数据库连接），各落库点独立提交。
     */
    public SseEmitter executeSyncStream(ReviewSyncRequest request) {
        metrics.recordSubmit();
        metrics.recordSync();

        String taskId = resolveOrGenerateTaskId(request);
        request.setTaskId(taskId);

        ReviewTask task = ReviewTask.fromRequest(taskId, request);
        task.setStatus(ReviewTaskStatus.PROCESSING);
        task.setTraceId(resolveTraceId());
        taskRepo.saveOrUpdate(task);

        log.info("Executing streaming sync review taskId={}", taskId);

        SseEmitter emitter = new SseEmitter(STREAM_EMITTER_TIMEOUT_MS);
        long start = System.currentTimeMillis();
        AtomicInteger seq = new AtomicInteger();
        AtomicReference<Disposable> subscriptionRef = new AtomicReference<>();

        StreamContext ctx = new StreamContext(task, emitter, seq, start, subscriptionRef);
        emitter.onCompletion(() -> log.debug("Stream completed taskId={}", taskId));
        emitter.onError(e -> log.debug("Stream error callback taskId={}: {}", taskId, e.getMessage()));
        emitter.onTimeout(() -> {
            log.warn("Stream emitter timeout taskId={}", taskId);
            Disposable subscription = subscriptionRef.get();
            if (subscription != null && !subscription.isDisposed()) {
                subscription.dispose();
            }
        });

        Disposable subscription = pythonClient.computeSyncStream(request).subscribe(
                sse -> handleStreamEvent(ctx, sse),
                error -> handleStreamFailure(ctx, error),
                () -> emitter.complete()
        );
        subscriptionRef.set(subscription);

        return emitter;
    }

    private void handleStreamEvent(StreamContext ctx, ServerSentEvent<String> sse) {
        String taskId = ctx.task().getTaskId();
        String eventName = sse.event() != null ? sse.event() : "message";
        String data = sse.data() != null ? sse.data() : "{}";

        // 总预算检查：超过 sync-timeout-ms 则取消订阅并按超时失败落库
        long elapsed = System.currentTimeMillis() - ctx.start();
        if (elapsed > orchProps.syncTimeoutMs()) {
            cancelSubscription(ctx);
            String message = "Python stream exceeded budget of " + orchProps.syncTimeoutMs() + "ms";
            handlePythonFailure(ctx.task(), "PYTHON_TIMEOUT", message);
            sendEvent(ctx, "run_error", errorPayload(taskId, "PYTHON_TIMEOUT", message));
            ctx.emitter().complete();
            return;
        }

        try {
            switch (eventName) {
                case "run_finished" -> {
                    ReviewStreamFinishedEvent terminal =
                            objectMapper.readValue(data, ReviewStreamFinishedEvent.class);
                    if (terminal == null || terminal.result() == null) {
                        throw new IOException("run_finished event missing result payload");
                    }
                    finishStreamingReview(ctx, terminal.result());
                }
                case "run_error" -> {
                    ReviewStreamErrorEvent error =
                            objectMapper.readValue(data, ReviewStreamErrorEvent.class);
                    String errorCode = error.errorCode() != null ? error.errorCode() : "PYTHON_SERVICE_ERROR";
                    handlePythonFailure(ctx.task(), errorCode, error.errorMessage());
                    sendEvent(ctx, "run_error", data);
                    ctx.emitter().complete();
                }
                default -> sendEvent(ctx, eventName, data);
            }
        } catch (IOException e) {
            // 终态事件 JSON 解析失败：按服务异常失败落库并终止流
            log.error("Failed to parse terminal stream event taskId={} event={}", taskId, eventName, e);
            handlePythonFailure(ctx.task(), "PYTHON_SERVICE_ERROR", "Malformed terminal event: " + e.getMessage());
            sendEvent(ctx, "run_error", errorPayload(taskId, "PYTHON_SERVICE_ERROR", "Malformed terminal event"));
            ctx.emitter().complete();
        }
    }

    /** run_finished 终态处理：与旧同步路径一致的收尾（后处理/落库/审计），随后转发并结束流。 */
    private void finishStreamingReview(StreamContext ctx, ReviewSyncResponse response) {
        String taskId = ctx.task().getTaskId();
        long latency = System.currentTimeMillis() - ctx.start();

        MarkdownImageProcessor.processImages(response, MINIO_ENDPOINT_PLACEHOLDER, MINIO_IMAGE_BUCKET);

        metrics.recordPythonLatency(latency);
        metrics.recordComplete();
        metrics.recordSyncLatency(latency);

        ReviewTaskStatus prevStatus = ctx.task().getStatus();
        ctx.task().setStatus(ReviewTaskStatus.SUCCESS);
        taskRepo.saveOrUpdate(ctx.task());
        response.setTaskId(taskId);

        ReviewResult result = ReviewResult.fromResponse(ctx.task(), response);
        resultRepo.upsert(result);

        writeAudit(taskId,
                prevStatus != null ? prevStatus.name() : null,
                ReviewTaskStatus.SUCCESS.name(),
                "SYSTEM",
                "Python streaming call completed, latency=" + latency + "ms");

        // 终态转发处理后的 result（图片 URL 已替换），而非 Python 原始载荷
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("result", response);
        sendEvent(ctx, "run_finished", writeJson(payload));
        ctx.emitter().complete();
    }

    /** 流异常终止（连接失败/空闲超时/HTTP 错误）：失败落库并尽力通知前端。 */
    private void handleStreamFailure(StreamContext ctx, Throwable error) {
        String taskId = ctx.task().getTaskId();
        String errorCode;
        String message;
        if (error instanceof PythonTimeoutException
                || error instanceof java.util.concurrent.TimeoutException) {
            errorCode = "PYTHON_TIMEOUT";
            message = "Python stream timed out (idle or budget): " + error.getMessage();
        } else if (error instanceof PythonServiceException) {
            errorCode = "PYTHON_SERVICE_ERROR";
            message = error.getMessage();
        } else {
            errorCode = "PYTHON_COMPUTE_FAILED";
            message = error.getMessage();
        }
        log.error("Streaming sync review failed taskId={} errorCode={}", taskId, errorCode, error);
        handlePythonFailure(ctx.task(), errorCode, message);
        sendEvent(ctx, "run_error", errorPayload(taskId, errorCode, message));
        ctx.emitter().complete();
    }

    /** 转发事件到前端：事件 ID 按 taskId 维度单调递增（taskId-seq），支持客户端去重。 */
    private void sendEvent(StreamContext ctx, String eventName, String data) {
        String taskId = ctx.task().getTaskId();
        String eventId = null;

        // write-through：先写入事件缓存（Redis RecordId 作为事件 ID 的唯一权威），再实时转发
        if (eventStore.enabled() && !"heartbeat".equals(eventName)) {
            eventId = eventStore.append(taskId, eventName, data);
        }
        if (eventId == null) {
            // Redis 不可用等降级路径：退回本地 seq 生成的事件 ID，实时转发不受影响
            eventId = taskId + "-" + ctx.seq().incrementAndGet();
        }
        // 终态事件写入后切换为长保留 TTL，支持断线重连窗口
        if (eventStore.enabled() && ("run_finished".equals(eventName) || "run_error".equals(eventName))) {
            eventStore.markTerminal(taskId);
        }

        try {
            ctx.emitter().send(SseEmitter.event()
                    .id(eventId)
                    .name(eventName)
                    .data(data));
        } catch (IOException | IllegalStateException e) {
            // 客户端已断开：不取消订阅，落库流程继续；流转发静默失败
            log.debug("SSE forward failed taskId={} event={}: {}",
                    taskId, eventName, e.getMessage());
        }
    }

    private void cancelSubscription(StreamContext ctx) {
        Disposable subscription = ctx.subscriptionRef().get();
        if (subscription != null && !subscription.isDisposed()) {
            subscription.dispose();
        }
    }

    private String errorPayload(String taskId, String errorCode, String message) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("errorCode", errorCode);
        payload.put("errorMessage", message != null ? message : "");
        return writeJson(payload);
    }

    private String writeJson(Map<String, Object> payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** 流式执行过程的上下文（请求级状态，随订阅回调传递）。 */
    private record StreamContext(
            ReviewTask task,
            SseEmitter emitter,
            AtomicInteger seq,
            long start,
            AtomicReference<Disposable> subscriptionRef) {
    }
}
