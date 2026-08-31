package com.acme.review.entity;

import com.acme.review.dto.ReviewSyncResponse;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;

@Data
@NoArgsConstructor
@TableName("review_result")
public class ReviewResult {
    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("risk_score")
    private BigDecimal riskScore;

    @TableField("risk_summary")
    private String riskSummary;

    @TableField("need_human_review")
    private boolean needHumanReview;

    @TableField("details")
    private String details;

    @TableField("logs")
    private String logs;

    @TableField("error_code")
    private String errorCode;

    @TableField("error_message")
    private String errorMessage;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;

    public static ReviewResult fromResponse(ReviewTask task, ReviewSyncResponse response) {
        ReviewResult result = new ReviewResult();
        result.setTaskId(task.getTaskId());
        result.setRiskScore(BigDecimal.valueOf(response.getRiskScore()));
        result.setRiskSummary(response.getRiskSummary());
        result.setNeedHumanReview(response.isNeedHumanReview());
        result.setDetails(String.join("\n", response.getDetails()));
        return result;
    }
}
