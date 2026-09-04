package com.acme.review.mq;

import com.acme.review.dto.ReviewCallbackMessage;
import com.acme.review.entity.ConsumedMessage;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.SseRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.support.MessageBuilder;

import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReviewCallbackConsumerTest {

    private ReviewTaskMapper taskRepo;
    private ReviewResultMapper resultRepo;
    private TaskAuditLogMapper auditLogMapper;
    private ConsumedMessageMapper consumedMessageMapper;
    private SseRegistry sseRegistry;
    private ConcurrentMetricsService metrics;
    private Consumer<org.springframework.messaging.Message<ReviewCallbackMessage>> fn;

    @BeforeEach
    void setUp() {
        taskRepo = mock(ReviewTaskMapper.class);
        resultRepo = mock(ReviewResultMapper.class);
        auditLogMapper = mock(TaskAuditLogMapper.class);
        consumedMessageMapper = mock(ConsumedMessageMapper.class);
        sseRegistry = mock(SseRegistry.class);
        metrics = mock(ConcurrentMetricsService.class);
        ReviewCallbackConsumer consumer = new ReviewCallbackConsumer(
                taskRepo, resultRepo, auditLogMapper, consumedMessageMapper, sseRegistry, metrics);
        fn = consumer.reviewCallbackIn();
    }

    @Test
    void shouldDriveProcessingToSuccessOnResultCallback() {
        ReviewTask task = task(taskId(), ReviewTaskStatus.PROCESSING);
        when(taskRepo.findByTaskId(taskId())).thenReturn(Optional.of(task));
        when(consumedMessageMapper.selectById(any())).thenReturn(null);

        fn.accept(message(resultCallback("SUCCEEDED")));

        verify(taskRepo).saveOrUpdate(argThat(t -> t.getStatus() == ReviewTaskStatus.SUCCESS));
        verify(resultRepo).upsert(argThat(r -> r.getTaskId().equals(taskId()) && r.getRiskScore() != null));
        verify(sseRegistry).send(eq(taskId()), eq("result"), any());
        verify(consumedMessageMapper).insert(argThat((ConsumedMessage m) -> true));
        verify(metrics).recordComplete();
    }

    @Test
    void shouldMapNeedReviewToHumanReviewStatus() {
        ReviewTask task = task(taskId(), ReviewTaskStatus.PROCESSING);
        when(taskRepo.findByTaskId(taskId())).thenReturn(Optional.of(task));
        when(consumedMessageMapper.selectById(any())).thenReturn(null);

        fn.accept(message(resultCallback("NEED_REVIEW")));

        verify(taskRepo).saveOrUpdate(argThat(t -> t.getStatus() == ReviewTaskStatus.HUMAN_REVIEW));
    }

    @Test
    void shouldMarkFailedOnDeadLetterCallback() {
        ReviewTask task = task(taskId(), ReviewTaskStatus.PROCESSING);
        when(taskRepo.findByTaskId(taskId())).thenReturn(Optional.of(task));
        when(consumedMessageMapper.selectById(any())).thenReturn(null);

        ReviewCallbackMessage callback = new ReviewCallbackMessage();
        callback.setMessageId("msg-dl");
        callback.setEventType("DEAD_LETTER");
        callback.setTaskId(taskId());
        callback.setErrorCode("EMPTY_DIFF");
        callback.setErrorMessage("diff is empty");
        fn.accept(message(callback));

        verify(taskRepo).saveOrUpdate(argThat(t -> t.getStatus() == ReviewTaskStatus.FAILED));
        verify(resultRepo).upsert(argThat(r -> "EMPTY_DIFF".equals(r.getErrorCode())));
        verify(sseRegistry).send(eq(taskId()), eq("task_failed"), any());
        verify(metrics).recordFailure();
    }

    @Test
    void shouldTransitionToProcessingOnProcessingCallback() {
        ReviewTask task = task(taskId(), ReviewTaskStatus.PENDING);
        when(taskRepo.findByTaskId(taskId())).thenReturn(Optional.of(task));
        when(consumedMessageMapper.selectById(any())).thenReturn(null);

        ReviewCallbackMessage callback = new ReviewCallbackMessage();
        callback.setMessageId("msg-processing");
        callback.setEventType("PROCESSING");
        callback.setTaskId(taskId());
        fn.accept(message(callback));

        verify(taskRepo).saveOrUpdate(argThat(t -> t.getStatus() == ReviewTaskStatus.PROCESSING));
        verify(sseRegistry).send(eq(taskId()), eq("status"), any());
    }

    @Test
    void shouldSkipDuplicateMessageId() {
        when(consumedMessageMapper.selectById("msg-dup")).thenReturn(new ConsumedMessage());

        ReviewCallbackMessage callback = new ReviewCallbackMessage();
        callback.setMessageId("msg-dup");
        callback.setEventType("RESULT");
        callback.setTaskId(taskId());
        callback.setResult(result("SUCCEEDED"));
        fn.accept(message(callback));

        verify(taskRepo, never()).findByTaskId(any());
        verify(taskRepo, never()).saveOrUpdate(any());
        verify(consumedMessageMapper, never()).insert(argThat((ConsumedMessage m) -> true));
    }

    @Test
    void shouldIgnoreResultForAlreadyTerminalTask() {
        ReviewTask task = task(taskId(), ReviewTaskStatus.SUCCESS);
        when(taskRepo.findByTaskId(taskId())).thenReturn(Optional.of(task));
        when(consumedMessageMapper.selectById(any())).thenReturn(null);

        fn.accept(message(resultCallback("SUCCEEDED")));

        verify(taskRepo, never()).saveOrUpdate(any());
        verify(resultRepo, never()).upsert(any());
    }

    private String taskId() {
        return "task-callback-1";
    }

    private ReviewTask task(String id, ReviewTaskStatus status) {
        ReviewTask task = new ReviewTask();
        task.setId(1L);
        task.setTaskId(id);
        task.setStatus(status);
        return task;
    }

    private org.springframework.messaging.Message<ReviewCallbackMessage> message(ReviewCallbackMessage callback) {
        return MessageBuilder.withPayload(callback).build();
    }

    private ReviewCallbackMessage resultCallback(String status) {
        ReviewCallbackMessage callback = new ReviewCallbackMessage();
        callback.setMessageId("msg-" + status.toLowerCase());
        callback.setEventType("RESULT");
        callback.setTaskId(taskId());
        callback.setResult(result(status));
        return callback;
    }

    private ReviewCallbackMessage.CallbackResult result(String status) {
        ReviewCallbackMessage.CallbackResult result = new ReviewCallbackMessage.CallbackResult();
        result.setTaskId(taskId());
        result.setStatus(status);
        result.setRiskScore(88.5);
        result.setRiskSummary("high risk detected");
        result.setNeedHumanReview(false);
        result.setDetails(List.of("SQL injection risk", "Missing index"));
        return result;
    }
}
