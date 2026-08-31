package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

/**
 * Diff 内容载荷表实体 —— 从 review_task 主表拆分的 LONGTEXT 大字段，
 * 避免常规查询加载大文本导致 IO 膨胀。
 */
@Data
@NoArgsConstructor
@TableName("review_task_payload")
public class ReviewTaskPayload {

    @TableField("task_id")
    private String taskId;

    @TableField("diff_content")
    private String diffContent;

    @TableField("created_at")
    private Instant createdAt;

    @TableField("updated_at")
    private Instant updatedAt;
}
