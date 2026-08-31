package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@TableName("task_audit_log")
public class TaskAuditLog {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("from_status")
    private String fromStatus;

    @TableField("to_status")
    private String toStatus;

    @TableField("operator")
    private String operator;

    @TableField("detail")
    private String detail;

    @TableField("created_at")
    private Instant createdAt;
}
