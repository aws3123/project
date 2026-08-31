package com.acme.review.service;

import com.acme.review.dto.HandoffDecision;
import com.acme.review.dto.HandoffRequest;
import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.dto.TaskListResponse;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class ReviewService {

    private static final String BUSINESS_RISK_SOURCE = "BUSINESS_RISK_SOURCE";

    private final ReviewTaskMapper reviewTaskMapper;
    private final ReviewResultMapper reviewResultMapper;
    private final BusinessRiskMetricsService businessRiskMetricsService;

    public Optional<TaskDetailResponse> getTaskDetail(String taskId) {
        return reviewTaskMapper.findByTaskId(taskId)
                .map(task -> {
                    ReviewResult result = reviewResultMapper.findByTaskId(taskId).orElse(null);
                    return TaskDetailResponse.from(task, result);
                });
    }

    public TaskListResponse listTasks(int page, int size, String projectId, String status) {
        LambdaQueryWrapper<ReviewTask> wrapper = new LambdaQueryWrapper<>();
        if (projectId != null && !projectId.isBlank()) {
            wrapper.eq(ReviewTask::getProjectId, projectId);
        }
        if (status != null && !status.isBlank()) {
            wrapper.eq(ReviewTask::getStatus, ReviewTaskStatus.fromDbValue(status));
        }
        wrapper.orderByDesc(ReviewTask::getCreatedAt);

        Page<ReviewTask> pageResult = reviewTaskMapper.selectPage(new Page<>(page, size), wrapper);
        List<TaskDetailResponse.TaskInfo> items = pageResult.getRecords().stream()
                .map(TaskDetailResponse.TaskInfo::from)
                .toList();
        return TaskListResponse.of(items, pageResult.getTotal(), page, size);
    }

    public Optional<TaskDetailResponse> getHandoff(String taskId) {
        return getTaskDetail(taskId);
    }

    @Transactional(rollbackFor = Exception.class)
    public Optional<TaskDetailResponse> submitHandoff(String taskId, HandoffRequest request) {
        return reviewTaskMapper.findByTaskId(taskId).map(task -> {
            ReviewTaskStatus previousStatus = task.getStatus();
            if (previousStatus != ReviewTaskStatus.HUMAN_REVIEW) {
                throw new IllegalStateException("task is not in HUMAN_REVIEW status");
            }

            ReviewTaskStatus targetStatus = mapDecisionToStatus(request.getDecision());
            task.setHandoffDecision(request.getDecision().name());
            task.setHandoffOperator(request.getOperator());
            task.setHandoffComment(request.getComment());
            task.setHandoffHandledAt(Instant.now());
            task.setStatus(targetStatus);

            reviewTaskMapper.saveOrUpdate(task);
            if (isBusinessRiskSource(task)) {
                businessRiskMetricsService.recordTransition(previousStatus, targetStatus);
                businessRiskMetricsService.recordClosed(targetStatus, "handoff");
                businessRiskMetricsService.recordPipelineLatency(task.getCreatedAt());
            }

            ReviewResult result = reviewResultMapper.findByTaskId(taskId).orElse(null);
            return TaskDetailResponse.from(task, result);
        });
    }

    private ReviewTaskStatus mapDecisionToStatus(HandoffDecision decision) {
        return switch (decision) {
            case APPROVED -> ReviewTaskStatus.SUCCESS;
            case REJECTED -> ReviewTaskStatus.FAILED;
            case CHANGES_REQUESTED -> throw new IllegalArgumentException("CHANGES_REQUESTED is not supported for handoff submission");
        };
    }

    private boolean isBusinessRiskSource(ReviewTask task) {
        return BUSINESS_RISK_SOURCE.equalsIgnoreCase(task.getMode());
    }
}
