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
@TableName("outbox_event")
public class OutboxEvent {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("event_id")
    private String eventId;

    @TableField("aggregate_type")
    private String aggregateType;

    @TableField("aggregate_id")
    private String aggregateId;

    @TableField("event_type")
    private String eventType;

    @TableField("payload")
    private String payload;

    @TableField("status")
    private String status;

    @TableField("retry_count")
    private Integer retryCount;

    @TableField("created_at")
    private Instant createdAt;

    @TableField("sent_at")
    private Instant sentAt;

    @TableField("updated_at")
    private Instant updatedAt;
}
