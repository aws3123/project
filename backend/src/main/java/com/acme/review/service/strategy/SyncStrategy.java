package com.acme.review.service.strategy;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.SseRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 同步审核执行策略。
 */
@Slf4j
@Component("syncReviewStrategy")
public class SyncStrategy extends AbstractReviewExecutionStrategy {

    public SyncStrategy(ReviewTaskMapper taskRepo,
                        ReviewResultMapper resultRepo,
                        PythonComputeClient pythonClient,
                        ConcurrentMetricsService metrics,
                        SseRegistry sseRegistry,
                        OrchestratorProperties orchProps,
                        TaskAuditLogMapper auditLogMapper) {
        super(taskRepo, resultRepo, pythonClient, metrics, sseRegistry, orchProps, auditLogMapper);
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
}
