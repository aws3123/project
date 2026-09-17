package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

/** 人工审核前的标准化历史事故草稿。 */
@Data
@NoArgsConstructor
@TableName("incident_record_draft")
public class IncidentRecordDraft {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("feedback_id")
    private Long feedbackId;

    @TableField("task_id")
    private String taskId;

    /** INCOMPLETE | PENDING_REVIEW | INGESTING | APPROVED | REJECTED | INGEST_FAILED */
    @TableField("status")
    private String status;

    @TableField("feedback_snapshot_json")
    private String feedbackSnapshotJson;

    @TableField("ast_snapshot_json")
    private String astSnapshotJson;

    @TableField("review_snapshot_json")
    private String reviewSnapshotJson;

    @TableField("incident_content")
    private String incidentContent;

    @TableField("rejection_reason")
    private String rejectionReason;

    @TableField("reviewer")
    private String reviewer;

    @TableField("reviewed_at")
    private Instant reviewedAt;

    @TableField("ingested_at")
    private Instant ingestedAt;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;

    @TableField(value = "updated_at", fill = FieldFill.INSERT_UPDATE)
    private Instant updatedAt;
}
