package com.acme.review.mq;

import com.acme.review.dto.ReviewCallbackMessage;
import com.acme.review.entity.ConsumedMessage;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.SseRegistry;
import com.acme.review.service.TokenUsageService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Topic 2 回调消费者 —— 驱动 Java 侧状态机、结果落库、SSE 推送与死信处理。
 *
 * <p>原 Java 消费者（{@code reviewTaskIn}）下线后，任务状态流转的职责移交到这里：
 * Python 消费 Topic 1 后通过 Topic 2 回投 PROCESSING / RESULT / DEAD_LETTER 事件，
 * 本消费者负责 PENDING → PROCESSING → SUCCESS / HUMAN_REVIEW / FAILED。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReviewCallbackConsumer {

    private static final String TRACE_ID_KEY = "traceId";
    private static final String MESSAGE_ID_KEY = "messageId";
    private static final String PROCESSING = "PROCESSING";
    private static final String RESULT = "RESULT";
    private static final String DEAD_LETTER = "DEAD_LETTER";

    private final ReviewTaskMapper taskRepo;
    private final ReviewResultMapper resultRepo;
    private final TaskAuditLogMapper auditLogMapper;
    private final ConsumedMessageMapper consumedMessageMapper;
    private final SseRegistry sseRegistry;
    private final ConcurrentMetricsService metrics;
    private final TokenUsageService tokenUsageService;

    @Bean
    public Consumer<Message<ReviewCallbackMessage>> reviewCallbackIn() {
        return message -> {
            ReviewCallbackMessage callback = message.getPayload();
            String messageId = resolveMessageId(message, callback);
            if (messageId != null && consumedMessageMapper.selectById(messageId) != null) {
                log.debug("Duplicate callback ignored messageId={}", messageId);
                return;
            }

            String traceId = callback.getTraceId() != null && !callback.getTraceId().isBlank()
                    ? callback.getTraceId() : callback.getTaskId();
            try (var ignored = MDC.putCloseable(TRACE_ID_KEY, traceId)) {
                handle(callback);

                if (messageId != null) {
                    ConsumedMessage record = new ConsumedMessage();
                    record.setMessageId(messageId);
                    record.setTaskId(callback.getTaskId());
                    record.setConsumedAt(Instant.now());
                    consumedMessageMapper.insert(record);
                }
            } catch (Exception e) {
                log.error("Failed to process callback messageId={} taskId={}", messageId, callback.getTaskId(), e);
                throw e;
            }
        };
    }

    private void handle(ReviewCallbackMessage callback) {
        String taskId = callback.getTaskId();
        if (taskId == null || taskId.isBlank()) {
            log.warn("Callback ignored: missing taskId");
            return;
        }
        ReviewTask task = taskRepo.findByTaskId(taskId).orElse(null);
        if (task == null) {
            log.warn("Callback ignored: task not found taskId={}", taskId);
            return;
        }

        String eventType = callback.getEventType() == null ? "" : callback.getEventType();
        switch (eventType) {
            case PROCESSING -> handleProcessing(task);
            case RESULT -> handleResult(task, callback);
            case DEAD_LETTER -> handleDeadLetter(task, callback);
            default -> log.warn("Callback ignored: unsupported eventType={} taskId={}", eventType, taskId);
        }
    }

    private void handleProcessing(ReviewTask task) {
        if (task.getStatus() != null && task.getStatus().isTerminal()) {
            log.debug("PROCESSING callback ignored: task already terminal taskId={}", task.getTaskId());
            return;
        }
        String prev = task.getStatus() != null ? task.getStatus().name() : "UNKNOWN";
        task.setStatus(ReviewTaskStatus.PROCESSING);
        taskRepo.saveOrUpdate(task);
        writeAudit(task.getTaskId(), prev, ReviewTaskStatus.PROCESSING.name(),
                "CALLBACK", "Python picked up task (PROCESSING callback)");
        sseRegistry.send(task.getTaskId(), "status", Map.of("status", "PROCESSING", "taskId", task.getTaskId()));
        log.info("Task transitioned to PROCESSING via callback taskId={}", task.getTaskId());
    }

    private void handleResult(ReviewTask task, ReviewCallbackMessage callback) {
        if (task.getStatus() != null && task.getStatus().isTerminal()) {
            log.debug("RESULT callback ignored: task already terminal taskId={}", task.getTaskId());
            return;
        }
        ReviewCallbackMessage.CallbackResult result = callback.getResult();
        if (result == null) {
            log.warn("RESULT callback missing result payload taskId={}", task.getTaskId());
            return;
        }

        ReviewTaskStatus target = resolveResultStatus(result);
        String prev = task.getStatus() != null ? task.getStatus().name() : "UNKNOWN";
        task.setStatus(target);
        taskRepo.saveOrUpdate(task);

        ReviewResult reviewResult = new ReviewResult();
        reviewResult.setTaskId(task.getTaskId());
        if (result.getRiskSummary() != null) {
            reviewResult.setRiskScore(BigDecimal.valueOf(result.getRiskScore()));
        }
        reviewResult.setRiskSummary(result.getRiskSummary());
        reviewResult.setNeedHumanReview(result.isNeedHumanReview());
        if (result.getDetails() != null) {
            reviewResult.setDetails(String.join("\n", result.getDetails()));
        }
        resultRepo.upsert(reviewResult);

        // 记账：Python 侧采集的真实 token 用量随回调落库
        tokenUsageService.record(task, callback.getUsage());

        writeAudit(task.getTaskId(), prev, target.name(), "CALLBACK", "Python completed review (RESULT callback)");
        if (target == ReviewTaskStatus.FAILED) {
            metrics.recordFailure();
        } else {
            metrics.recordComplete();
        }

        Map<String, Object> sseData = Map.of(
                "taskId", task.getTaskId(),
                "riskScore", result.getRiskScore(),
                "riskSummary", result.getRiskSummary() != null ? result.getRiskSummary() : "",
                "needHumanReview", result.isNeedHumanReview(),
                "details", result.getDetails() != null ? result.getDetails() : java.util.List.of()
        );
        sseRegistry.send(task.getTaskId(), "result", sseData);
        log.info("Task transitioned to {} via callback taskId={}", target, task.getTaskId());
    }

    private void handleDeadLetter(ReviewTask task, ReviewCallbackMessage callback) {
        if (task.getStatus() != null && task.getStatus().isTerminal()) {
            log.debug("DEAD_LETTER callback ignored: task already terminal taskId={}", task.getTaskId());
            return;
        }
        String prev = task.getStatus() != null ? task.getStatus().name() : "UNKNOWN";
        task.setStatus(ReviewTaskStatus.FAILED);
        taskRepo.saveOrUpdate(task);

        ReviewResult result = new ReviewResult();
        result.setTaskId(task.getTaskId());
        result.setErrorCode(callback.getErrorCode() != null ? callback.getErrorCode() : "MQ_DEAD_LETTER");
        result.setErrorMessage(callback.getErrorMessage() != null ? callback.getErrorMessage()
                : "Task landed in dead letter via callback");
        resultRepo.upsert(result);

        writeAudit(task.getTaskId(), prev, ReviewTaskStatus.FAILED.name(),
                "CALLBACK", "DEAD_LETTER: " + callback.getErrorCode());
        metrics.recordFailure();
        sseRegistry.send(task.getTaskId(), "task_failed", Map.of(
                "taskId", task.getTaskId(),
                "status", "FAILED",
                "errorCode", result.getErrorCode(),
                "traceId", task.getTraceId() != null ? task.getTraceId() : ""
        ));
        log.warn("Task marked FAILED via DEAD_LETTER callback taskId={} code={}",
                task.getTaskId(), callback.getErrorCode());
    }

    private ReviewTaskStatus resolveResultStatus(ReviewCallbackMessage.CallbackResult result) {
        String status = result.getStatus() == null ? "" : result.getStatus().trim().toUpperCase();
        if ("NEED_REVIEW".equals(status) || "HUMAN_REVIEW".equals(status)) {
            return ReviewTaskStatus.HUMAN_REVIEW;
        }
        if ("FAILED".equals(status) || "ERROR".equals(status)) {
            return ReviewTaskStatus.FAILED;
        }
        return ReviewTaskStatus.SUCCESS;
    }

    private String resolveMessageId(Message<?> message, ReviewCallbackMessage callback) {
        String fromPayload = callback.getMessageId();
        if (fromPayload != null && !fromPayload.isBlank()) {
            return fromPayload;
        }
        return message.getHeaders().get(MESSAGE_ID_KEY, String.class);
    }

    private void writeAudit(String taskId, String from, String to, String operator, String detail) {
        TaskAuditLog log = new TaskAuditLog();
        log.setTaskId(taskId);
        log.setFromStatus(from);
        log.setToStatus(to);
        log.setOperator(operator);
        log.setDetail(detail);
        log.setCreatedAt(Instant.now());
        auditLogMapper.insert(log);
    }
}
