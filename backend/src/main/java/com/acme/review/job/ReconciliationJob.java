package com.acme.review.job;

import com.acme.review.config.OrchestratorProperties;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskPayload;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.ReviewTaskPayloadMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 最终一致性兜底 Job。
 * 1. 扫描 PENDING 超过 30 分钟的卡住任务 → 重建 Outbox 事件
 * 2. 扫描 PROCESSING 超过 2x asyncTimeout 的任务 → 标记 FAILED
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReconciliationJob {

    private static final Duration STUCK_PENDING_THRESHOLD = Duration.ofMinutes(30);
    private static final int BATCH_SIZE = 50;

    private final ReviewTaskMapper taskRepo;
    private final OutboxEventMapper outboxMapper;
    private final ReviewResultMapper resultRepo;
    private final TaskAuditLogMapper auditLogMapper;
    private final ReviewTaskPayloadMapper payloadMapper;
    private final OrchestratorProperties orchProps;
    private final ObjectMapper objectMapper;

    /**
     * 每分钟执行一次兜底扫描。
     */
    @Scheduled(fixedDelay = 60_000)
    public void reconcile() {
        reconcileStuckPending();
        reconcileStuckProcessing();
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void reconcileStuckPending() {
        Instant threshold = Instant.now().minus(STUCK_PENDING_THRESHOLD);
        List<ReviewTask> stuckTasks = taskRepo.selectList(
                new LambdaQueryWrapper<ReviewTask>()
                        .eq(ReviewTask::getStatus, ReviewTaskStatus.PENDING)
                        .lt(ReviewTask::getCreatedAt, threshold)
                        .last("LIMIT " + BATCH_SIZE)
        );

        for (ReviewTask task : stuckTasks) {
            long pendingEvents = outboxMapper.selectCount(
                    new LambdaQueryWrapper<OutboxEvent>()
                            .eq(OutboxEvent::getAggregateId, task.getTaskId())
                            .eq(OutboxEvent::getStatus, "PENDING")
            );

            if (pendingEvents == 0) {
                if ("BUSINESS_RISK_SOURCE".equalsIgnoreCase(task.getMode())) {
                    markBusinessRiskMissingOutboxFailed(task);
                    continue;
                }

                OutboxEvent event = new OutboxEvent();
                event.setEventId(UUID.randomUUID().toString());
                event.setAggregateType("review_task");
                event.setAggregateId(task.getTaskId());
                event.setStatus("PENDING");
                event.setRetryCount(0);
                event.setCreatedAt(Instant.now());
                event.setEventType("TASK_RECONCILED");
                event.setPayload(buildReconciledPayload(task));
                outboxMapper.insert(event);

                writeAudit(task.getTaskId(), "PENDING", "PENDING",
                        "RECONCILIATION", "Rebuilt missing outbox event");

                log.warn("Reconciled stuck PENDING task taskId={} mode={}", task.getTaskId(), task.getMode());
            }
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void reconcileStuckProcessing() {
        long timeoutMs = orchProps.asyncTimeoutMs() * 2L;
        Instant threshold = Instant.now().minusMillis(timeoutMs);
        List<ReviewTask> timedOutTasks = taskRepo.selectList(
                new LambdaQueryWrapper<ReviewTask>()
                        .eq(ReviewTask::getStatus, ReviewTaskStatus.PROCESSING)
                        .lt(ReviewTask::getUpdatedAt, threshold)
                        .last("LIMIT " + BATCH_SIZE)
        );

        for (ReviewTask task : timedOutTasks) {
            task.setStatus(ReviewTaskStatus.FAILED);
            taskRepo.updateById(task);

            ReviewResult result = new ReviewResult();
            result.setTaskId(task.getTaskId());
            result.setErrorCode("RECONCILIATION_TIMEOUT");
            result.setErrorMessage("Task stuck in PROCESSING for longer than " + timeoutMs + "ms");
            resultRepo.upsert(result);

            writeAudit(task.getTaskId(), "PROCESSING", "FAILED",
                    "RECONCILIATION", "Timed out after " + timeoutMs + "ms");

            log.warn("Reconciliation marked stuck PROCESSING task as FAILED taskId={}", task.getTaskId());
        }
    }

    private void markBusinessRiskMissingOutboxFailed(ReviewTask task) {
        task.setStatus(ReviewTaskStatus.FAILED);
        taskRepo.updateById(task);

        ReviewResult result = new ReviewResult();
        result.setTaskId(task.getTaskId());
        result.setErrorCode("BUSINESS_RISK_OUTBOX_MISSING");
        result.setErrorMessage("Business risk task missing dispatch outbox payload for reconciliation");
        resultRepo.upsert(result);

        writeAudit(task.getTaskId(), "PENDING", "FAILED",
                "RECONCILIATION", "Business risk task missing dispatch outbox payload");

        log.warn("Reconciliation marked business risk task as FAILED due to missing outbox taskId={}", task.getTaskId());
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

    private String buildReconciledPayload(ReviewTask task) {
        String diffContent = payloadMapper.findByTaskId(task.getTaskId())
                .map(ReviewTaskPayload::getDiffContent)
                .orElse("");
        // 使用 ObjectMapper 安全序列化，避免手动拼接 JSON 的转义问题
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "taskId", task.getTaskId(),
                    "projectId", task.getProjectId() != null ? task.getProjectId() : "",
                    "projectName", task.getProjectName() != null ? task.getProjectName() : "",
                    "prUrl", task.getPrUrl() != null ? task.getPrUrl() : "",
                    "diffContent", diffContent,
                    "traceId", task.getTraceId() != null ? task.getTraceId() : "",
                    "mode", task.getMode() != null ? task.getMode() : "ASYNC"
            ));
        } catch (Exception e) {
            log.error("Failed to serialize reconciled payload taskId={}", task.getTaskId(), e);
            return "{\"taskId\":\"" + task.getTaskId() + "\",\"diffContent\":\"\"}";
        }
    }
}
