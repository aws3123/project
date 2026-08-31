package com.acme.review.mq;

import com.acme.review.dto.ReviewTaskMessage;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.function.Consumer;

/**
 * 死信队列消费器。
 * 超过最大重试次数的消息落入 DLQ 后，由本消费者标记任务为 FAILED 并记录审计。
 */
@Slf4j
@RequiredArgsConstructor
@Component
public class DlqConsumer {

    private static final String TRACE_ID_KEY = "traceId";

    private final ReviewTaskMapper taskRepo;
    private final ReviewResultMapper resultRepo;
    private final TaskAuditLogMapper auditLogMapper;

    @Bean
    public Consumer<Message<ReviewTaskMessage>> reviewTaskDlqIn() {
        return message -> {
            ReviewTaskMessage payload = message.getPayload();
            String taskId = payload.getTaskId();
            String traceId = message.getHeaders().get(TRACE_ID_KEY, String.class);

            try (var ignored = MDC.putCloseable(TRACE_ID_KEY, traceId)) {
                log.warn("Task landed in DLQ taskId={}", taskId);

                ReviewTask task = taskRepo.findByTaskId(taskId).orElse(null);
                if (task != null && !task.getStatus().isTerminal()) {
                    String prevStatus = task.getStatus() != null ? task.getStatus().name() : "UNKNOWN";
                    task.setStatus(ReviewTaskStatus.FAILED);
                    taskRepo.saveOrUpdate(task);

                    ReviewResult failedResult = new ReviewResult();
                    failedResult.setTaskId(taskId);
                    failedResult.setErrorCode("MQ_RETRY_EXHAUSTED");
                    failedResult.setErrorMessage("Message exceeded retry limit and was sent to DLQ");
                    resultRepo.upsert(failedResult);

                    TaskAuditLog audit = new TaskAuditLog();
                    audit.setTaskId(taskId);
                    audit.setFromStatus(prevStatus);
                    audit.setToStatus(ReviewTaskStatus.FAILED.name());
                    audit.setOperator("DLQ_CONSUMER");
                    audit.setDetail("Message exceeded retry limit");
                    audit.setCreatedAt(Instant.now());
                    auditLogMapper.insert(audit);
                }
            } catch (Exception e) {
                log.error("Failed to process DLQ message taskId={}", taskId, e);
                throw e;
            }
        };
    }
}
