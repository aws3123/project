package com.acme.review.mq;

import com.acme.review.dto.BusinessRiskPythonSourceRequest;
import com.acme.review.dto.BusinessRiskPythonSourceResponse;
import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.acme.review.dto.ReviewTaskMessage;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.exception.BusinessRiskDispatchGateException;
import com.acme.review.exception.PythonHttpException;
import com.acme.review.exception.PythonTimeoutException;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.BusinessRiskMetricsService;
import com.acme.review.service.BusinessRiskTaskService;
import com.acme.review.service.BusinessRiskWorkerRegistryService;
import com.acme.review.service.SseRegistry;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

@Slf4j
@Component
@RequiredArgsConstructor
public class OutboxPoller {

    private static final String ASYNC_OUTPUT_BINDING = "reviewTask-out-0";
    private static final String TRACE_ID_KEY = "traceId";
    private static final String BUSINESS_RISK_DISPATCH_EVENT = "BUSINESS_RISK_DISPATCH";
    private static final String MESSAGE_ID_KEY = "messageId";
    private static final int BATCH_SIZE = 20;
    private static final int MAX_POLL_RETRY = 10;

    private final OutboxEventMapper outboxMapper;
    private final StreamBridge streamBridge;
    private final ObjectMapper objectMapper;
    private final BusinessRiskTaskService businessRiskTaskService;
    private final BusinessRiskWorkerRegistryService workerRegistryService;
    private final BusinessRiskMetricsService metricsService;
    private final ReviewTaskMapper reviewTaskMapper;
    private final ReviewResultMapper reviewResultMapper;
    private final TaskAuditLogMapper auditLogMapper;
    private final SseRegistry sseRegistry;

    @Scheduled(fixedDelay = 2000)
    public void poll() {
        List<OutboxEvent> events = fetchPendingEvents();
        if (events.isEmpty()) {
            return;
        }

        for (OutboxEvent event : events) {
            sendEvent(event);
        }
    }

    private List<OutboxEvent> fetchPendingEvents() {
        LambdaQueryWrapper<OutboxEvent> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(OutboxEvent::getStatus, "PENDING")
                .orderByAsc(OutboxEvent::getCreatedAt)
                .last("LIMIT " + BATCH_SIZE + " FOR UPDATE SKIP LOCKED");
        return outboxMapper.selectList(wrapper);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void sendEvent(OutboxEvent event) {
        String traceId = resolveTraceId(event);
        try (var ignored = MDC.putCloseable(TRACE_ID_KEY, traceId)) {
            try {
                if (BUSINESS_RISK_DISPATCH_EVENT.equals(event.getEventType())) {
                    sendBusinessRiskDispatch(event);
                } else {
                    sendReviewTaskEvent(event);
                }
            } catch (Exception e) {
                log.error("Outbox send failed eventId={} aggregateId={} eventType={}",
                        event.getEventId(), event.getAggregateId(), event.getEventType(), e);
                event.setStatus("FAILED");
                event.setRetryCount((event.getRetryCount() == null ? 0 : event.getRetryCount()) + 1);

                if (event.getRetryCount() >= MAX_POLL_RETRY) {
                    log.error("Outbox event {} exceeded max retry, marking DEAD", event.getEventId());
                    if (BUSINESS_RISK_DISPATCH_EVENT.equals(event.getEventType())) {
                        markBusinessRiskDispatchExhausted(event, e);
                    } else {
                        markReviewTaskExhausted(event, e);
                    }
                    event.setStatus("DEAD");
                }
            }
            outboxMapper.updateById(event);
        }
    }

    private void markBusinessRiskDispatchExhausted(OutboxEvent event, Exception cause) {
        try {
            BusinessRiskPythonSourceRequest request = readBusinessRiskRequest(event);
            String traceId = request.getTraceId() == null || request.getTraceId().isBlank() ? resolveTraceId(event) : request.getTraceId();
            String errorCode = "PYTHON_DISPATCH_RETRY_EXHAUSTED";
            if (cause instanceof BusinessRiskDispatchGateException gateException) {
                errorCode = gateException.getErrorCode();
            }
            businessRiskTaskService.markBusinessRiskDispatchFailed(
                    request.getTaskId(),
                    request.getSessionId(),
                    traceId,
                    errorCode,
                    cause.getMessage()
            );
        } catch (Exception parseException) {
            log.warn("Failed to mark business risk dispatch exhausted eventId={}", event.getEventId(), parseException);
        }
    }

    private void markReviewTaskExhausted(OutboxEvent event, Exception cause) {
        try {
            ReviewTaskMessage message = objectMapper.readValue(event.getPayload(), ReviewTaskMessage.class);
            String taskId = message.getTaskId();
            ReviewTask task = reviewTaskMapper.findByTaskId(taskId).orElse(null);
            if (task == null || (task.getStatus() != null && task.getStatus().isTerminal())) {
                return;
            }
            task.setStatus(ReviewTaskStatus.FAILED);
            reviewTaskMapper.saveOrUpdate(task);

            ReviewResult result = new ReviewResult();
            result.setTaskId(taskId);
            result.setErrorCode("OUTBOX_DELIVERY_EXHAUSTED");
            result.setErrorMessage(
                    "Outbox delivery failed after " + MAX_POLL_RETRY + " attempts: " + cause.getMessage());
            reviewResultMapper.upsert(result);

            TaskAuditLog audit = new TaskAuditLog();
            audit.setTaskId(taskId);
            audit.setFromStatus(task.getStatus().name());
            audit.setToStatus(ReviewTaskStatus.FAILED.name());
            audit.setOperator("OUTBOX_POLLER");
            audit.setDetail("Outbox event " + event.getEventId() + " hit DEAD");
            audit.setCreatedAt(Instant.now());
            auditLogMapper.insert(audit);

            sseRegistry.send(taskId, "task_failed", Map.of(
                    "taskId", taskId,
                    "status", "FAILED",
                    "errorCode", "OUTBOX_DELIVERY_EXHAUSTED",
                    "traceId", message.getTraceId() != null ? message.getTraceId() : ""
            ));
            log.warn("Review task marked FAILED due to outbox DEAD taskId={}", taskId);
        } catch (Exception parseException) {
            log.warn("Failed to mark review task exhausted eventId={}", event.getEventId(), parseException);
        }
    }

    private void sendReviewTaskEvent(OutboxEvent event) throws Exception {
        ReviewTaskMessage taskMessage = objectMapper.readValue(event.getPayload(), ReviewTaskMessage.class);

        Message<ReviewTaskMessage> msg = MessageBuilder
                .withPayload(taskMessage)
                .setHeader(TRACE_ID_KEY, taskMessage.getTraceId())
                .setHeader(MESSAGE_ID_KEY, event.getEventId())
                .build();

        boolean sent = streamBridge.send(ASYNC_OUTPUT_BINDING, msg);
        if (sent) {
            event.setStatus("SENT");
            event.setSentAt(Instant.now());
            return;
        }

        event.setStatus("FAILED");
        event.setRetryCount((event.getRetryCount() == null ? 0 : event.getRetryCount()) + 1);
    }

    private void sendBusinessRiskDispatch(OutboxEvent event) throws Exception {
        BusinessRiskPythonSourceRequest request = readBusinessRiskRequest(event);
        String traceId = request.getTraceId() == null || request.getTraceId().isBlank() ? resolveTraceId(event) : request.getTraceId();
        if (traceId != null && !traceId.isBlank()) {
            request.setTraceId(traceId);
        }

        BusinessRiskWorkerRegistrySnapshot snapshot = workerRegistryService.snapshot(request.getSchemaVersion(), request.getJavaPreprocessVersion());
        metricsService.recordWorkerSnapshot(snapshot);
        if (!snapshot.isDispatchAllowed()) {
            metricsService.recordDispatchBlocked(snapshot.getBlockReason());
            throw new BusinessRiskDispatchGateException(snapshot.getBlockReason(), "Business risk dispatch blocked: " + snapshot.getBlockReason());
        }

        try {
            BusinessRiskPythonSourceResponse response = businessRiskTaskService.analyzeSource(request);
            businessRiskTaskService.handlePythonSourceResponse(
                    request.getTaskId(),
                    request.getSessionId(),
                    traceId,
                    response
            );
            event.setStatus("SENT");
            event.setSentAt(Instant.now());
            metricsService.recordDispatchAttempt("SUCCESS");
        } catch (PythonHttpException ex) {
            metricsService.recordDispatchAttempt("PYTHON_HTTP_ERROR");
            if (!ex.isRetryable()) {
                businessRiskTaskService.markBusinessRiskDispatchFailed(
                        request.getTaskId(),
                        request.getSessionId(),
                        traceId,
                        "PYTHON_DISPATCH_FAILED",
                        ex.getMessage()
                );
                event.setStatus("DEAD");
                event.setRetryCount(MAX_POLL_RETRY);
                return;
            }
            throw ex;
        } catch (PythonTimeoutException ex) {
            metricsService.recordDispatchAttempt("TIMEOUT");
            throw ex;
        }
    }

    private BusinessRiskPythonSourceRequest readBusinessRiskRequest(OutboxEvent event) throws Exception {
        JsonNode payloadNode = objectMapper.readTree(event.getPayload());
        if (payloadNode != null && payloadNode.isTextual()) {
            return objectMapper.readValue(payloadNode.textValue(), BusinessRiskPythonSourceRequest.class);
        }
        return objectMapper.treeToValue(payloadNode, BusinessRiskPythonSourceRequest.class);
    }

    private String resolveTraceId(OutboxEvent event) {
        String fromMdc = MDC.get(TRACE_ID_KEY);
        if (fromMdc != null && !fromMdc.isBlank()) {
            return fromMdc;
        }
        return event.getAggregateId();
    }
}
