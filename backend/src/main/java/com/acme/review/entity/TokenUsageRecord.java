package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Token 用量记录：Python 层 LLM 真实 usage 经 RESULT 回调落库。
 *
 * <p>单价（{@code unitPriceSnapshot}）在记账时取配置快照，
 * 避免后续调价导致历史账目金额漂移。</p>
 */
@Data
@NoArgsConstructor
@TableName(value = "token_usage_record")
public class TokenUsageRecord {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("submitter")
    private String submitter;

    @TableField("model")
    private String model;

    @TableField("prompt_tokens")
    private Integer promptTokens;

    @TableField("completion_tokens")
    private Integer completionTokens;

    @TableField("total_tokens")
    private Integer totalTokens;

    /** 单价快照（元/千 token），防止调价后历史账目漂移 */
    @TableField("unit_price_snapshot")
    private BigDecimal unitPriceSnapshot;

    /** 本次调用费用 = total_tokens * unit_price_snapshot / 1000 */
    @TableField("cost_amount")
    private BigDecimal costAmount;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;
}
