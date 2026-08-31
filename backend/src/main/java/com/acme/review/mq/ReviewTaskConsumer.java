package com.acme.review.mq;

import com.acme.review.dto.ReviewTaskMessage;
import com.acme.review.entity.ConsumedMessage;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.service.strategy.AsyncStrategy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.function.Consumer;

@Slf4j
@RequiredArgsConstructor
@Component
public class ReviewTaskConsumer {

    private static final String TRACE_ID_KEY = "traceId";
    private static final String MESSAGE_ID_KEY = "messageId";

    private final AsyncStrategy asyncStrategy;
    private final ConsumedMessageMapper consumedMessageMapper;

    @Bean
    public Consumer<Message<ReviewTaskMessage>> reviewTaskIn() {
        return message -> {
            String messageId = message.getHeaders().get(MESSAGE_ID_KEY, String.class);
            if (messageId != null && consumedMessageMapper.selectById(messageId) != null) {
                log.info("Duplicate message ignored messageId={}", messageId);
                return;
            }

            String traceId = message.getHeaders().get(TRACE_ID_KEY, String.class);
            try (var ignored = MDC.putCloseable(TRACE_ID_KEY, traceId)) {
                log.info("Consumed async review task from MQ traceId={} messageId={}", traceId, messageId);
                asyncStrategy.processAsyncTask(message.getPayload());

                if (messageId != null) {
                    ConsumedMessage record = new ConsumedMessage();
                    record.setMessageId(messageId);
                    record.setTaskId(message.getPayload().getTaskId());
                    record.setConsumedAt(Instant.now());
                    consumedMessageMapper.insert(record);
                }
            } catch (Exception e) {
                log.error("Failed to process async task, will be retried or sent to DLQ", e);
                throw e;
            }
        };
    }
}
