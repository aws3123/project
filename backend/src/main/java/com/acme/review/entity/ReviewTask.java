package com.acme.review.entity;

import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;

import lombok.Data;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Data
@NoArgsConstructor
@TableName(value = "review_task", autoResultMap = true)
public class ReviewTask {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("project_id")
    private String projectId;

    @TableField("project_name")
    private String projectName;

    @TableField("submitter")
    private String submitter;

    @TableField(value = "status", typeHandler = ReviewTaskStatusTypeHandler.class)
    private ReviewTaskStatus status;

    @TableField("mode")
    private String mode;

    @TableField("priority")
    private String priority;

    @TableField("trace_id")
    private String traceId;

    @TableField("handoff_decision")
    private String handoffDecision;

    @TableField("handoff_operator")
    private String handoffOperator;

    @TableField("handoff_comment")
    private String handoffComment;

    @TableField("handoff_handled_at")
    private Instant handoffHandledAt;

    @TableField("retry_count")
    private Integer retryCount;

    @Version
    @TableField("version")
    private Integer version;

    @TableField("pr_url")
    private String prUrl;

    @TableField("question")
    private String question;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;

    @TableField(value = "updated_at", fill = FieldFill.INSERT_UPDATE)
    private Instant updatedAt;

    public static ReviewTask fromRequest(String taskId, ReviewSyncRequest request) {
        ReviewTask task = new ReviewTask();
        task.setTaskId(taskId);
        task.setProjectId(request.getProjectId());
        task.setProjectName(request.getProjectName());
        task.setPrUrl(request.getPrUrl());
        task.setQuestion(request.getQuestion());
        task.setSubmitter(request.getSubmitter());
        task.setStatus(ReviewTaskStatus.PENDING);
        task.setMode(request.getMode() != null ? request.getMode().name() : ReviewMode.SYNC.name());
        return task;
    }
}
