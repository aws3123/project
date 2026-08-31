package com.acme.review.dto;

import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;

import java.math.BigDecimal;
import java.time.Instant;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class TaskDetailResponse {

    private TaskInfo task;
    private ResultInfo result;

    public static TaskDetailResponse from(ReviewTask task, ReviewResult result) {
        TaskDetailResponse response = new TaskDetailResponse();
        response.setTask(TaskInfo.from(task));
        response.setResult(ResultInfo.from(result));
        return response;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class TaskInfo {
        private String taskId;
        private String projectId;
        private String projectName;
        private String status;
        private String mode;
        private String traceId;
        private String handoffDecision;
        private String handoffOperator;
        private String handoffComment;
        private Instant handoffHandledAt;
        private String prUrl;
        private Instant createdAt;
        private Instant updatedAt;

        public static TaskInfo from(ReviewTask task) {
            TaskInfo info = new TaskInfo();
            info.setTaskId(task.getTaskId());
            info.setProjectId(task.getProjectId());
            info.setProjectName(task.getProjectName());
            info.setStatus(task.getStatus() != null ? task.getStatus().name() : null);
            info.setMode(task.getMode());
            info.setTraceId(task.getTraceId());
            info.setHandoffDecision(task.getHandoffDecision());
            info.setHandoffOperator(task.getHandoffOperator());
            info.setHandoffComment(task.getHandoffComment());
            info.setHandoffHandledAt(task.getHandoffHandledAt());
            info.setPrUrl(task.getPrUrl());
            info.setCreatedAt(task.getCreatedAt());
            info.setUpdatedAt(task.getUpdatedAt());
            return info;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class ResultInfo {
        private BigDecimal riskScore;
        private String riskSummary;
        private boolean needHumanReview;
        private String errorCode;
        private String errorMessage;
        private Instant createdAt;

        public static ResultInfo from(ReviewResult result) {
            if (result == null) {
                return null;
            }
            ResultInfo info = new ResultInfo();
            info.setRiskScore(result.getRiskScore());
            info.setRiskSummary(result.getRiskSummary());
            info.setNeedHumanReview(result.isNeedHumanReview());
            info.setErrorCode(result.getErrorCode());
            info.setErrorMessage(result.getErrorMessage());
            info.setCreatedAt(result.getCreatedAt());
            return info;
        }
    }
}
