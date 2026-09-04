package com.acme.review.service.strategy;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.dto.ReviewAsyncResponse;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewTaskMessage;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskPayload;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.exception.AsyncDispatchException;
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
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * 异步审核执行策略（Outbox 发布）。
 * 任务下发到 Kafka 后由 Python 消费，处理结果通过回调 topic 驱动 Java 状态机
 * （见 {@code ReviewCallbackConsumer}），本策略不再持有消费侧逻辑。
 */
@Slf4j
@Component("asyncReviewStrategy")
public class AsyncStrategy extends AbstractReviewExecutionStrategy {

    private static final String TRACE_ID_KEY = "traceId";
    private static final int MAX_RETRY_COUNT = 3;

    private final StreamBridge streamBridge;
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
                         OutboxEventMapper outboxMapper,
                         ReviewTaskPayloadMapper payloadMapper,
                         ObjectMapper objectMapper) {
        super(taskRepo, resultRepo, pythonClient, metrics, sseRegistry, orchProps, auditLogMapper);
        this.streamBridge = streamBridge;
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

        // diff 内容 + AST 预处理产物拆分到独立载荷表，避免主表查询膨胀、避免 MQ 大消息
        if (request.getDiffContent() != null && !request.getDiffContent().isBlank()) {
            ReviewTaskPayload payload = new ReviewTaskPayload();
            payload.setTaskId(taskId);
            payload.setDiffContent(request.getDiffContent());
            payload.setEntitiesJson(writeJsonOrNull(request.getEntities()));
            payload.setRelationsJson(writeJsonOrNull(request.getRelations()));
            payload.setCreatedAt(Instant.now());
            payloadMapper.insert(payload);
        }

        ReviewTaskMessage taskMessage = new ReviewTaskMessage(
                taskId,
                request.getProjectId(),
                request.getProjectName(),
                request.getPrUrl(),
                traceId,
                request.getSessionId(),
                request.getMode() != null ? request.getMode().name() : ReviewMode.ASYNC.name()
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

        ReviewTaskMessage taskMessage = new ReviewTaskMessage(
                taskId,
                task.getProjectId(),
                task.getProjectName(),
                task.getPrUrl(),
                task.getTraceId(),
                null,
                task.getMode()
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

    private String writeJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            throw new AsyncDispatchException(null, "Failed to serialize outbox payload", e);
        }
    }

    private String writeJsonOrNull(Object obj) {
        if (obj == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.warn("Failed to serialize payload field, storing null", e);
            return null;
        }
    }
}
