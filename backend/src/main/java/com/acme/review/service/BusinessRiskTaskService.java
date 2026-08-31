package com.acme.review.service;

import com.acme.review.client.BusinessRiskPythonClient;
import com.acme.review.dto.BusinessRiskCallbackRequest;
import com.acme.review.dto.BusinessRiskPreparedSubmission;
import com.acme.review.dto.BusinessRiskPythonSourceRequest;
import com.acme.review.dto.BusinessRiskPythonSourceResponse;
import com.acme.review.dto.BusinessRiskSourceMetadataRequest;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.exception.BusinessRiskPreprocessException;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class BusinessRiskTaskService {

    private static final String BUSINESS_RISK_DISPATCH_EVENT = "BUSINESS_RISK_DISPATCH";

    private final ReviewTaskMapper reviewTaskMapper;
    private final ReviewResultMapper reviewResultMapper;
    private final OutboxEventMapper outboxEventMapper;
    private final BusinessRiskSseService sseService;
    private final BusinessRiskPythonClient businessRiskPythonClient;
    private final BusinessRiskMetricsService metricsService;
    private final BusinessRiskSourcePreprocessService preprocessService;
    private final SessionMemoryService sessionMemoryService;
    private final ObjectMapper objectMapper;

    @Value("${business-risk.callback.url:http://localhost:8080/api/internal/business-risk/callback}")
    private String callbackUrl;

    @Value("${business-risk.callback.token-header:X-Callback-Token}")
    private String callbackTokenHeader;

    @Value("${business-risk.callback.signature-header:X-Callback-Signature}")
    private String callbackSignatureHeader;

    @Value("${business-risk.callback.timestamp-header:X-Callback-Timestamp}")
    private String callbackTimestampHeader;

    @Value("${business-risk.callback.nonce-header:X-Callback-Nonce}")
    private String callbackNonceHeader;

    @Value("${security.callback-token:dev-callback}")
    private String callbackToken;

    @Value("${business-risk.source.java-preprocess-version:3.0}")
    private String javaPreprocessVersion;

    public String createTask(BusinessRiskSourceMetadataRequest request) {
        String taskId = request.getRequestId() != null && !request.getRequestId().isBlank()
                ? request.getRequestId()
                : "biz-risk-" + UUID.randomUUID();

        ReviewTask task = reviewTaskMapper.findByTaskId(taskId).orElseGet(ReviewTask::new);
        if (task.getId() == null) {
            task.setTaskId(taskId);
            task.setProjectId(request.getProjectId());
            task.setProjectName(request.getRepo() + ":" + request.getBranch());
            task.setMode("BUSINESS_RISK_SOURCE");
            task.setTraceId(request.getTraceId());
            task.setStatus(ReviewTaskStatus.PENDING);
            reviewTaskMapper.saveOrUpdate(task);
            metricsService.recordCreated();
        }

        return taskId;
    }

    public String resolveSessionId(String taskId) {
        return "session-" + taskId;
    }

    public ReviewTaskStatus dispatchToPythonAsync(BusinessRiskSourceMetadataRequest request, List<MultipartFile> files, String taskId, String sessionId) {
        String traceId = request.getTraceId() != null && !request.getTraceId().isBlank()
                ? request.getTraceId()
                : reviewTaskMapper.findByTaskId(taskId)
                .map(ReviewTask::getTraceId)
                .orElse(taskId);

        try {
            BusinessRiskPreparedSubmission preparedSubmission = preprocessService.prepare(request, files);
            BusinessRiskPythonSourceRequest pythonRequest = BusinessRiskPythonSourceRequest.from(
                    request,
                    preparedSubmission,
                    javaPreprocessVersion,
                    taskId,
                    sessionId,
                    traceId,
                    callbackUrl,
                    callbackTokenHeader,
                    callbackToken,
                    callbackSignatureHeader,
                    callbackTimestampHeader,
                    callbackNonceHeader
            );
            metricsService.recordPreprocess(
                    preparedSubmission.getRawTotalBytes(),
                    preparedSubmission.getPreparedTotalBytes(),
                    pythonRequest.getSourcePackage() != null && pythonRequest.getSourcePackage().getBudget() != null
                            ? pythonRequest.getSourcePackage().getBudget().getDecision()
                            : "UNKNOWN"
            );

            reviewTaskMapper.findByTaskId(taskId).ifPresent(task -> {
                ReviewTaskStatus previousStatus = task.getStatus();
                task.setStatus(ReviewTaskStatus.PROCESSING);
                if ((task.getTraceId() == null || task.getTraceId().isBlank()) && traceId != null && !traceId.isBlank()) {
                    task.setTraceId(traceId);
                }
                reviewTaskMapper.saveOrUpdate(task);
                metricsService.recordTransition(previousStatus, ReviewTaskStatus.PROCESSING);
            });
            sseService.publish(sessionId, taskId, "task_processing", "{\"status\":\"PROCESSING\",\"traceId\":\"" + traceId + "\"}");
            enqueueDispatchOutbox(taskId, pythonRequest);
            return ReviewTaskStatus.PROCESSING;
        } catch (BusinessRiskPreprocessException ex) {
            metricsService.recordPreprocessFailure(ex.getErrorCode());
            markPreprocessFailed(taskId, sessionId, traceId, ex.getErrorCode(), ex.getMessage());
            throw ex;
        }
    }

    public BusinessRiskPythonSourceResponse analyzeSource(BusinessRiskPythonSourceRequest request) {
        return businessRiskPythonClient.analyzeSource(request);
    }

    public void handlePythonSourceResponse(String taskId, String sessionId, String traceId, BusinessRiskPythonSourceResponse response) {
        handlePythonResponseFallback(taskId, sessionId, traceId, response);
    }

    public void markBusinessRiskDispatchFailed(String taskId, String sessionId, String traceId, String errorCode, String errorMessage) {
        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId(taskId);
        callback.setSessionId(sessionId);
        callback.setSuccess(false);
        callback.setStatus("failed");
        callback.setErrorCode(errorCode);
        callback.setErrorMessage(errorMessage);
        callback.setTraceId(traceId != null && !traceId.isBlank() ? traceId : taskId);
        handleCallback(callback);
    }

    private void markPreprocessFailed(String taskId, String sessionId, String traceId, String errorCode, String errorMessage) {
        reviewTaskMapper.findByTaskId(taskId).ifPresent(task -> {
            ReviewTaskStatus previousStatus = task.getStatus();
            task.setStatus(ReviewTaskStatus.FAILED);
            task.setTraceId(traceId);
            reviewTaskMapper.saveOrUpdate(task);
            metricsService.recordTransition(previousStatus, ReviewTaskStatus.FAILED);
            metricsService.recordClosed(ReviewTaskStatus.FAILED, "preprocess");
            metricsService.recordPipelineLatency(task.getCreatedAt());
        });

        ReviewResult result = reviewResultMapper.findByTaskId(taskId).orElseGet(ReviewResult::new);
        result.setTaskId(taskId);
        result.setNeedHumanReview(false);
        result.setRiskScore(null);
        result.setRiskSummary(null);
        result.setDetails(null);
        result.setLogs(null);
        result.setErrorCode(errorCode);
        result.setErrorMessage(errorMessage);
        reviewResultMapper.upsert(result);

        Map<String, Object> payload = new HashMap<>();
        payload.put("status", "FAILED");
        payload.put("taskId", taskId);
        payload.put("errorCode", errorCode);
        payload.put("traceId", traceId);
        sseService.publish(sessionId, taskId, "task_failed", writeJson(payload));
    }

    private void enqueueDispatchOutbox(String taskId, BusinessRiskPythonSourceRequest pythonRequest) {
        OutboxEvent outboxEvent = new OutboxEvent();
        outboxEvent.setEventId(UUID.randomUUID().toString());
        outboxEvent.setAggregateType("business_risk_task");
        outboxEvent.setAggregateId(taskId);
        outboxEvent.setEventType(BUSINESS_RISK_DISPATCH_EVENT);
        outboxEvent.setPayload(writeJson(pythonRequest));
        outboxEvent.setStatus("PENDING");
        outboxEvent.setRetryCount(0);
        outboxEvent.setCreatedAt(Instant.now());
        outboxEventMapper.insert(outboxEvent);
        log.info("Business risk dispatch queued via outbox taskId={} eventId={}", taskId, outboxEvent.getEventId());
    }

    private void handlePythonResponseFallback(String taskId, String sessionId, String traceId, BusinessRiskPythonSourceResponse response) {
        if (response == null || response.getStatus() == null || response.getStatus().isBlank()) {
            return;
        }

        String status = response.getStatus().trim().toLowerCase();
        boolean completed = "completed".equals(status) || "success".equals(status);
        boolean failed = "failed".equals(status) || "error".equals(status);
        boolean humanReview = "human_review".equals(status) || "need_review".equals(status);

        if (!completed && !failed && !humanReview) {
            return;
        }

        ReviewTask task = reviewTaskMapper.findByTaskId(taskId).orElse(null);
        if (task != null && task.getStatus() != null && task.getStatus().isTerminal()) {
            return;
        }

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId(response.getTaskId() != null && !response.getTaskId().isBlank() ? response.getTaskId() : taskId);
        callback.setRunId(response.getRunId());
        callback.setSessionId(sessionId);
        callback.setStatus(status);
        callback.setSuccess(completed || humanReview);
        if (failed) {
            callback.setErrorCode("PYTHON_ANALYSIS_FAILED");
            callback.setErrorMessage("Python source analysis returned failed status");
        }
        callback.setTraceId(response.getTraceId() != null && !response.getTraceId().isBlank() ? response.getTraceId() : traceId);
        callback.setReport(response.getReport());
        callback.setProposedMemoryUpdates(response.getProposedMemoryUpdates());
        handleCallback(callback);
    }

    public void handleCallback(BusinessRiskCallbackRequest callback) {
        String taskId = callback.resolvedTaskId();
        if (taskId == null || taskId.isBlank()) {
            log.warn("Business risk callback ignored: missing task id");
            return;
        }

        ReviewTask task = reviewTaskMapper.findByTaskId(taskId).orElse(null);
        if (task == null) {
            log.warn("Business risk callback ignored: task not found taskId={}", taskId);
            return;
        }

        ReviewTaskStatus currentStatus = task.getStatus() == null ? ReviewTaskStatus.PENDING : task.getStatus();
        ReviewTaskStatus targetStatus = resolveTargetStatus(callback);
        if (targetStatus == null) {
            log.warn("Business risk callback ignored: unsupported status taskId={} status={} success={}",
                    taskId, callback.getStatus(), callback.getSuccess());
            return;
        }

        if (currentStatus.isTerminal()) {
            if (currentStatus != targetStatus) {
                log.warn("Business risk callback ignored: terminal status cannot rollback taskId={} current={} target={}",
                        taskId, currentStatus, targetStatus);
            }
            return;
        }

        if (!isTransitionAllowed(currentStatus, targetStatus)) {
            log.warn("Business risk callback ignored: illegal transition taskId={} current={} target={}",
                    taskId, currentStatus, targetStatus);
            return;
        }

        task.setStatus(targetStatus);
        if (callback.getTraceId() != null && !callback.getTraceId().isBlank()) {
            task.setTraceId(callback.getTraceId());
        } else if (task.getTraceId() == null || task.getTraceId().isBlank()) {
            task.setTraceId(taskId);
        }
        reviewTaskMapper.saveOrUpdate(task);
        metricsService.recordTransition(currentStatus, targetStatus);

        ReviewResult result = reviewResultMapper.findByTaskId(taskId).orElseGet(ReviewResult::new);
        result.setTaskId(taskId);

        String sessionId = callback.getSessionId() != null && !callback.getSessionId().isBlank()
                ? callback.getSessionId()
                : "session-" + taskId;

        if (targetStatus == ReviewTaskStatus.SUCCESS || targetStatus == ReviewTaskStatus.HUMAN_REVIEW) {
            String riskSummary = resolveRiskSummary(callback);
            result.setRiskSummary(riskSummary);
            result.setRiskScore(callback.getRiskScore());
            result.setNeedHumanReview(targetStatus == ReviewTaskStatus.HUMAN_REVIEW);
            result.setDetails(writeJson(callback.getReport()));
            result.setLogs(writeJson(callback.getProposedMemoryUpdates()));
            result.setErrorCode(null);
            result.setErrorMessage(null);

            Map<String, Object> ssePayload = new HashMap<>();
            ssePayload.put("status", targetStatus.name());
            ssePayload.put("taskId", taskId);
            ssePayload.put("riskSummary", riskSummary);
            ssePayload.put("traceId", task.getTraceId());
            String eventType = targetStatus == ReviewTaskStatus.HUMAN_REVIEW ? "task_human_review" : "task_completed";
            sseService.publish(sessionId, taskId, eventType, writeJson(ssePayload));
            if (targetStatus == ReviewTaskStatus.SUCCESS) {
                metricsService.recordClosed(targetStatus, "callback");
                metricsService.recordPipelineLatency(task.getCreatedAt());
            }
        } else {
            String errorCode = callback.getErrorCode() != null && !callback.getErrorCode().isBlank()
                    ? callback.getErrorCode()
                    : "BUSINESS_RISK_FAILED";
            result.setRiskSummary(null);
            result.setRiskScore(null);
            result.setNeedHumanReview(false);
            result.setDetails(null);
            result.setLogs(null);
            result.setErrorCode(errorCode);
            result.setErrorMessage(callback.getErrorMessage());

            Map<String, Object> ssePayload = new HashMap<>();
            ssePayload.put("status", "FAILED");
            ssePayload.put("taskId", taskId);
            ssePayload.put("errorCode", errorCode);
            ssePayload.put("traceId", task.getTraceId());
            sseService.publish(sessionId, taskId, "task_failed", writeJson(ssePayload));
            metricsService.recordClosed(targetStatus, "callback");
            metricsService.recordPipelineLatency(task.getCreatedAt());
        }

        // Persist proposed memory updates to Redis so Python can recover on reconnection
        sessionMemoryService.saveProposedUpdates(sessionId, callback.getProposedMemoryUpdates());

        reviewResultMapper.upsert(result);
    }

    private ReviewTaskStatus resolveTargetStatus(BusinessRiskCallbackRequest callback) {
        String status = callback.getStatus();
        if (status != null) {
            if ("human_review".equalsIgnoreCase(status) || "need_review".equalsIgnoreCase(status)) {
                return ReviewTaskStatus.HUMAN_REVIEW;
            }
            if ("failed".equalsIgnoreCase(status) || "error".equalsIgnoreCase(status)) {
                return ReviewTaskStatus.FAILED;
            }
            if ("completed".equalsIgnoreCase(status) || "success".equalsIgnoreCase(status)) {
                return ReviewTaskStatus.SUCCESS;
            }
        }
        if (Boolean.TRUE.equals(callback.getSuccess())) {
            return ReviewTaskStatus.SUCCESS;
        }
        if (Boolean.FALSE.equals(callback.getSuccess())) {
            return ReviewTaskStatus.FAILED;
        }
        return null;
    }

    private boolean isTransitionAllowed(ReviewTaskStatus current, ReviewTaskStatus target) {
        if (current == ReviewTaskStatus.PENDING) {
            return target == ReviewTaskStatus.PROCESSING
                    || target == ReviewTaskStatus.SUCCESS
                    || target == ReviewTaskStatus.FAILED
                    || target == ReviewTaskStatus.HUMAN_REVIEW;
        }
        if (current == ReviewTaskStatus.PROCESSING) {
            return target == ReviewTaskStatus.SUCCESS
                    || target == ReviewTaskStatus.FAILED
                    || target == ReviewTaskStatus.HUMAN_REVIEW;
        }
        return false;
    }

    private String resolveRiskSummary(BusinessRiskCallbackRequest callback) {
        if (callback.getRiskSummary() != null && !callback.getRiskSummary().isBlank()) {
            return callback.getRiskSummary();
        }
        String fromReport = extractExecutiveSummary(callback.getReport());
        if (fromReport != null && !fromReport.isBlank()) {
            return fromReport;
        }
        return "Business risk analysis completed";
    }

    private String extractExecutiveSummary(Map<String, Object> report) {
        if (report == null) {
            return null;
        }
        Object summary = report.get("executive_summary");
        if (summary instanceof String value) {
            return value;
        }
        return null;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of() : value);
        } catch (Exception e) {
            log.warn("Failed to serialize business risk payload", e);
            return "{}";
        }
    }
}
