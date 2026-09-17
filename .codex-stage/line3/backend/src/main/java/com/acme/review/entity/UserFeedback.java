package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@TableName("user_feedback")
public class UserFeedback {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("session_id")
    private String sessionId;

    @TableField("feedback_type")
    private String feedbackType;

    @TableField("category")
    private String category;

    @TableField("comment")
    private String comment;

    @TableField("metadata")
    private String metadata;

    @TableField("user_agent")
    private String userAgent;

    @TableField("source")
    private String source;

    @TableField("trace_id")
    private String traceId;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;
}
