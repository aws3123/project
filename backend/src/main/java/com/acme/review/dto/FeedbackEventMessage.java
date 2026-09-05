package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * 差评回流事件 —— 用户提交 thumbs_down 反馈后经 Outbox 投递到 ai.feedback.events。
 *
 * <p>消费方（Java FeedbackEventConsumer）据此写负样本审计与指标；
 * 后续 Python 质检复核也可订阅同一 topic 扩展。</p>
 */
@Getter
@Setter
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class FeedbackEventMessage {

    /** Outbox eventId，消费端幂等键 */
    private String messageId;

    private Long feedbackId;

    private String taskId;

    private String sessionId;

    /** 固定为 thumbs_down，字段保留以兼容未来扩展 */
    private String feedbackType;

    private String category;

    private String comment;

    private String source;

    private String traceId;
}
