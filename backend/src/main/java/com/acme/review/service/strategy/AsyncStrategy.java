package com.acme.review.service.strategy;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.dto.ReviewAsyncResponse;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.dto.ReviewTaskMessage;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskPayload;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.exception.AsyncDispatchException;
import com.acme.review.exception.PythonServiceException;
import com.acme.review.exception.PythonTimeoutException;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.ReviewTaskPayloadMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.SseRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * 异步审核执行策略（Outbox 发布 + 消费处理）。
 */
@Slf4j
@Component("asyncReviewStrategy")
public class AsyncStrategy extends AbstractReviewExecutionStrategy {

    private static final String ASYNC_OUTPUT_BINDING = "reviewTask-out-0";
    private static final String TRACE_ID_KEY = "traceId";
    private static final int MAX_RETRY_COUNT = 3;

    private final StreamBridge streamBridge;
    private final ThreadPoolExecutor reviewExecutor;
    private final OutboxEventMapper outboxMapper;
    private final ReviewTaskPayloadMapper payloadMapper;
    private final ObjectMapper objectMapper;

    public AsyncStrategy(ReviewTaskMapper taskRepo,
                         ReviewResultMapper resultRepo,
                         PythonComputeClient pythonClient,
                         ConcurrentMetricsService metrics,
                         SseRegistry sseRegistry,
                         OrchestratorProperties orchProps,
                         TaskAuditLogMapper auditLogMapper,
                         StreamBridge streamBridge,
                         ThreadPoolExecutor reviewExecutor,
                         OutboxEventMapper outboxMapper,
                         ReviewTaskPayloadMapper payloadMapper,
                         ObjectMapper objectMapper) {
        super(taskRepo, resultRepo, pythonClient, metrics, sseRegistry, orchProps, auditLogMapper);
        this.streamBridge = streamBridge;
        this.reviewExecutor = reviewExecutor;
        this.outboxMapper = outboxMapper;
        this.payloadMapper = payloadMapper;
        this.objectMapper = objectMapper;
    }

    /**
     * 发布异步任务：在同一本地事务中写入 review_task + outbox_event。
     * OutboxPoller 负责实际投递 MQ。
     */
    @Transactional(rollbackFor = Exception.class)
    public ReviewAsyncResponse publishAsync(ReviewSyncRequest request) {
        metrics.recordSubmit();
        metrics.recordAsync();

        String taskId = UUID.randomUUID().toString();
        String traceId = resolveTraceId();

        ReviewTask task = ReviewTask.fromRequest(taskId, request);
        task.setStatus(ReviewTaskStatus.PENDING);
        task.setTraceId(traceId);
        taskRepo.saveOrUpdate(task);

        // diff 内容拆分到独立载荷表，避免主表查询膨胀
        if (request.getDiffContent() != null && !request.getDiffContent().isBlank()) {
            ReviewTaskPayload payload = new ReviewTaskPayload();
            payload.setTaskId(taskId);
            payload.setDiffContent(request.getDiffContent());
            payload.setCreatedAt(Instant.now());
            payloadMapper.insert(payload);
        }

        ReviewTaskMessage taskMessage = new ReviewTaskMessage(
                taskId,
                request.getProjectId(),
                request.getProjectName(),
                request.getPrUrl(),
                request.getDiffContent(),
                traceId,
                request.getMode() != null ? request.getMode().name() : ReviewMode.ASYNC.name(),
                request.getEntities(),
                request.getRelations()
        );

        OutboxEvent event = new OutboxEvent();
        event.setEventId(UUID.randomUUID().toString());
        event.setAggregateType("review_task");
        event.setAggregateId(taskId);
        event.setEventType("TASK_CREATED");
        event.setPayload(writeJson(taskMessage));
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setCreatedAt(Instant.now());
        outboxMapper.insert(event);

        writeAudit(taskId, null, "PENDING", "SYSTEM", "Task created via outbox");

        log.info("Async review task persisted with outbox taskId={} traceId={}", taskId, traceId);
        sseRegistry.send(taskId, "status", Map.of("status", "QUEUED", "taskId", taskId));
        return new ReviewAsyncResponse(taskId, "QUEUED");
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW, rollbackFor = Exception.class)
    public void processAsyncTask(ReviewTaskMessage message) {
        long start = System.currentTimeMillis();
        String taskId = message.getTaskId();
        log.info("Processing async task from MQ taskId={} traceId={}", taskId, message.getTraceId());

        Optional<ReviewTask> optTask = taskRepo.findByTaskId(taskId);
        if (optTask.isEmpty()) {
            log.error("Task not found for async processing taskId={}", taskId);
            return;
        }

        ReviewTask task = optTask.get();
        if (task.getStatus() != ReviewTaskStatus.PENDING) {
            log.warn("Task {} already processed, current status={}", taskId, task.getStatus());
            return;
        }
        task.setStatus(ReviewTaskStatus.PROCESSING);
        taskRepo.saveOrUpdate(task);
        writeAudit(taskId, "PENDING", "PROCESSING", "MQ_CONSUMER", "Consumer picked up task");
        sseRegistry.send(taskId, "status", Map.of("status", "PROCESSING", "taskId", taskId));

        ReviewSyncRequest request = buildRequestFromMessage(message);

        executePythonCall(request, task,
                () -> {
                    CompletableFuture<ReviewSyncResponse> future = CompletableFuture
                            .supplyAsync(() -> pythonClient.computeAsync(request), reviewExecutor)
                            .exceptionally(ex -> {
                                log.error("Python async call failed taskId={}", taskId, ex);
                                throw new PythonServiceException("AI service unavailable", ex);
                            });
                    try {
                        return future.get(orchProps.asyncTimeoutMs() + 5000, TimeUnit.MILLISECONDS);
                    } catch (TimeoutException e) {
                        future.cancel(true);
                        throw new PythonTimeoutException(
                                "Async task timeout after " + orchProps.asyncTimeoutMs() + "ms", e);
                    }
                },
                (response, latency) -> {
                    metrics.recordAsyncLatency(latency);
                    return response.isNeedHumanReview()
                            ? ReviewTaskStatus.HUMAN_REVIEW : ReviewTaskStatus.SUCCESS;
                });

        long totalLatency = System.currentTimeMillis() - start;
        log.info("Async task completed taskId={} latencyMs={}", taskId, totalLatency);
    }

    /**
     * 重试失败任务：通过 Outbox 重新投递。
     */
    @Transactional(rollbackFor = Exception.class)
    public void retryStuckTask(String taskId) {
        ReviewTask task = taskRepo.findByTaskId(taskId)
                .orElseThrow(() -> new IllegalArgumentException("Task not found: " + taskId));

        if (task.getStatus() != ReviewTaskStatus.FAILED) {
            throw new IllegalStateException(
                    "Only FAILED tasks can be retried, current: " + task.getStatus());
        }

        int retryCount = task.getRetryCount() != null ? task.getRetryCount() : 0;
        if (retryCount >= MAX_RETRY_COUNT) {
            throw new IllegalStateException(
                    "Task " + taskId + " exceeded max retry count: " + MAX_RETRY_COUNT);
        }

        task.setStatus(ReviewTaskStatus.PENDING);
        task.setRetryCount(retryCount + 1);
        taskRepo.saveOrUpdate(task);
        writeAudit(taskId, "FAILED", "PENDING", "HUMAN", "Manual retry #" + (retryCount + 1));

        // 从载荷表读取 diff 内容
        String diffContent = payloadMapper.findByTaskId(taskId)
                .map(ReviewTaskPayload::getDiffContent)
                .orElse(null);

        ReviewTaskMessage taskMessage = new ReviewTaskMessage(
                taskId,
                task.getProjectId(),
                task.getProjectName(),
                task.getPrUrl(),
                diffContent,
                task.getTraceId(),
                task.getMode(),
                null,
                null
        );

        OutboxEvent event = new OutboxEvent();
        event.setEventId(UUID.randomUUID().toString());
        event.setAggregateType("review_task");
        event.setAggregateId(taskId);
        event.setEventType("TASK_RETRY");
        event.setPayload(writeJson(taskMessage));
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setCreatedAt(Instant.now());
        outboxMapper.insert(event);

        log.info("Retry queued via outbox taskId={}", taskId);
    }

    private ReviewSyncRequest buildRequestFromMessage(ReviewTaskMessage message) {
        ReviewSyncRequest request = new ReviewSyncRequest();
        request.setTaskId(message.getTaskId());
        request.setProjectId(message.getProjectId());
        request.setProjectName(message.getProjectName());
        request.setPrUrl(message.getPrUrl());
        request.setDiffContent(message.getDiffContent());
        request.setMode(ReviewMode.valueOf(message.getMode()));
        request.setEntities(message.getEntities());
        request.setRelations(message.getRelations());
        return request;
    }

    private String writeJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            throw new AsyncDispatchException(null, "Failed to serialize outbox payload", e);
        }
    }
}
