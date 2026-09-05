package com.acme.review.mq;

import com.acme.review.dto.FeedbackEventMessage;
import com.acme.review.entity.ConsumedMessage;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.function.Consumer;

/**
 * 差评回流消费者 —— 订阅 ai.feedback.events，将 thumbs_down 反馈转化为负样本标记。
 *
 * <p>职责：</p>
 * <ul>
 *   <li>写 task_audit_log 负样本标记（operator=FEEDBACK_ANALYZER），供人工质检与复盘检索</li>
 *   <li>Micrometer 计数 feedback_negative_total（按 source/category 打标），暴露反馈质量趋势</li>
 * </ul>
 *
 * <p>幂等：沿用 ConsumedMessage 去重表，messageId 取 Outbox eventId。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class FeedbackEventConsumer {

    private static final String TRACE_ID_KEY = "traceId";
    private static final String MESSAGE_ID_KEY = "messageId";
    private static final String METRIC_NAME = "feedback_negative_total";

    private final TaskAuditLogMapper auditLogMapper;
    private final ConsumedMessageMapper consumedMessageMapper;
    private final MeterRegistry meterRegistry;

    @Bean
    public Consumer<Message<FeedbackEventMessage>> feedbackEventIn() {
        return message -> {
            FeedbackEventMessage event = message.getPayload();
            String messageId = resolveMessageId(message, event);
            if (messageId != null && consumedMessageMapper.selectById(messageId) != null) {
                log.debug("Duplicate feedback event ignored messageId={}", messageId);
                return;
            }

            String traceId = event.getTraceId() != null && !event.getTraceId().isBlank()
                    ? event.getTraceId() : event.getTaskId();
            try (var ignored = MDC.putCloseable(TRACE_ID_KEY, traceId)) {
                handle(event);

                if (messageId != null) {
                    ConsumedMessage record = new ConsumedMessage();
                    record.setMessageId(messageId);
                    record.setTaskId(event.getTaskId());
                    record.setConsumedAt(Instant.now());
                    consumedMessageMapper.insert(record);
                }
            } catch (Exception e) {
                log.error("Failed to process feedback event messageId={} taskId={}", messageId, event.getTaskId(), e);
                throw e;
            }
        };
    }

    private void handle(FeedbackEventMessage event) {
        if (event.getTaskId() == null || event.getTaskId().isBlank()) {
            log.warn("Feedback event ignored: missing taskId");
            return;
        }

        TaskAuditLog audit = new TaskAuditLog();
        audit.setTaskId(event.getTaskId());
        audit.setFromStatus("N/A");
        audit.setToStatus("NEGATIVE_FEEDBACK");
        audit.setOperator("FEEDBACK_ANALYZER");
        audit.setDetail(buildDetail(event));
        audit.setCreatedAt(Instant.now());
        auditLogMapper.insert(audit);

        meterRegistry.counter(METRIC_NAME,
                "source", event.getSource() != null ? event.getSource() : "unknown",
                "category", event.getCategory() != null ? event.getCategory() : "unknown")
                .increment();

        log.info("Negative feedback marked taskId={} feedbackId={} category={}",
                event.getTaskId(), event.getFeedbackId(), event.getCategory());
    }

    private String buildDetail(FeedbackEventMessage event) {
        StringBuilder sb = new StringBuilder("差评负样本标记 feedbackId=")
                .append(event.getFeedbackId());
        if (event.getCategory() != null && !event.getCategory().isBlank()) {
            sb.append(" category=").append(event.getCategory());
        }
        if (event.getComment() != null && !event.getComment().isBlank()) {
            String comment = event.getComment().length() > 500
                    ? event.getComment().substring(0, 500) + "..." : event.getComment();
            sb.append(" comment=").append(comment);
        }
        return sb.toString();
    }

    private String resolveMessageId(Message<?> message, FeedbackEventMessage event) {
        if (event.getMessageId() != null && !event.getMessageId().isBlank()) {
            return event.getMessageId();
        }
        return message.getHeaders().get(MESSAGE_ID_KEY, String.class);
    }
}
