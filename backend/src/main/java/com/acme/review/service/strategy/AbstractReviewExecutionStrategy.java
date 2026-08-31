package com.acme.review.service.strategy;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.exception.PythonServiceException;
import com.acme.review.exception.PythonTimeoutException;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.SseRegistry;
import com.acme.review.util.MarkdownImageProcessor;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import org.slf4j.MDC;

import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.function.BiFunction;

/**
 * 审核执行策略抽象基类 —— 模板方法模式。
 * 封装 "调用 Python -> 成功处理 -> 失败处理" 的生命周期骨架，
 * 子类通过 {@link #executePythonCall} 注入具体的调用方式和状态解析逻辑。
 */
@AllArgsConstructor(access = AccessLevel.PROTECTED)
public abstract class AbstractReviewExecutionStrategy implements ReviewExecutionStrategy {

    private static final String TRACE_ID_KEY = "traceId";
    private static final String MINIO_ENDPOINT_PLACEHOLDER = "http://localhost:9000";
    private static final String MINIO_IMAGE_BUCKET = "incident-images";

    protected final ReviewTaskMapper taskRepo;
    protected final ReviewResultMapper resultRepo;
    protected final PythonComputeClient pythonClient;
    protected final ConcurrentMetricsService metrics;
    protected final SseRegistry sseRegistry;
    protected final OrchestratorProperties orchProps;
    protected final TaskAuditLogMapper auditLogMapper;

    /**
     * 模板方法：封装 Python 调用的完整生命周期。
     */
    protected ReviewSyncResponse executePythonCall(
            ReviewSyncRequest request,
            ReviewTask task,
            Callable<ReviewSyncResponse> pythonInvoker,
            BiFunction<ReviewSyncResponse, Long, ReviewTaskStatus> statusResolver) {

        long start = System.currentTimeMillis();
        try {
            ReviewSyncResponse response = pythonInvoker.call();
            MarkdownImageProcessor.processImages(response, MINIO_ENDPOINT_PLACEHOLDER, MINIO_IMAGE_BUCKET);
            long latency = System.currentTimeMillis() - start;

            metrics.recordPythonLatency(latency);
            metrics.recordComplete();

            ReviewTaskStatus prevStatus = task.getStatus();
            ReviewTaskStatus finalStatus = statusResolver.apply(response, latency);
            task.setStatus(finalStatus);
            taskRepo.saveOrUpdate(task);
            response.setTaskId(task.getTaskId());

            ReviewResult result = ReviewResult.fromResponse(task, response);
            resultRepo.upsert(result);
            sseRegistry.send(task.getTaskId(), "result", response);

            writeAudit(task.getTaskId(),
                    prevStatus != null ? prevStatus.name() : null,
                    finalStatus.name(),
                    "SYSTEM",
                    "Python call completed, latency=" + latency + "ms");

            return response;
        } catch (PythonTimeoutException e) {
            handlePythonFailure(task, "PYTHON_TIMEOUT", e.getMessage());
            throw e;
        } catch (PythonServiceException e) {
            handlePythonFailure(task, "PYTHON_SERVICE_ERROR", e.getMessage());
            throw e;
        } catch (Exception e) {
            handlePythonFailure(task, "PYTHON_COMPUTE_FAILED", e.getMessage());
            throw new PythonServiceException("Unexpected error during review", e);
        }
    }

    protected void handlePythonFailure(ReviewTask task, String errorCode, String errorMessage) {
        metrics.recordFailure();
        ReviewTaskStatus prevStatus = task.getStatus();
        task.setStatus(ReviewTaskStatus.FAILED);
        taskRepo.saveOrUpdate(task);
        ReviewResult result = new ReviewResult();
        result.setTaskId(task.getTaskId());
        result.setErrorCode(errorCode);
        result.setErrorMessage(errorMessage);
        resultRepo.upsert(result);

        writeAudit(task.getTaskId(),
                prevStatus != null ? prevStatus.name() : null,
                ReviewTaskStatus.FAILED.name(),
                "SYSTEM",
                errorCode + ": " + errorMessage);
    }

    protected void writeAudit(String taskId, String from, String to, String operator, String detail) {
        TaskAuditLog log = new TaskAuditLog();
        log.setTaskId(taskId);
        log.setFromStatus(from);
        log.setToStatus(to);
        log.setOperator(operator);
        log.setDetail(detail);
        log.setCreatedAt(Instant.now());
        auditLogMapper.insert(log);
    }

    protected String resolveTraceId() {
        String traceId = MDC.get(TRACE_ID_KEY);
        return (traceId != null && !traceId.isBlank()) ? traceId : UUID.randomUUID().toString();
    }

    protected String resolveOrGenerateTaskId(ReviewSyncRequest request) {
        return request.getTaskId() != null ? request.getTaskId() : UUID.randomUUID().toString();
    }
}
