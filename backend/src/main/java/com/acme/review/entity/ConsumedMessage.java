package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@TableName("consumed_message")
public class ConsumedMessage {

    @TableId("message_id")
    private String messageId;

    @TableField("task_id")
    private String taskId;

    @TableField("consumed_at")
    private Instant consumedAt;
}
