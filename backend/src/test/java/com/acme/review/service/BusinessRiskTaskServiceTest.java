package com.acme.review.service;

import com.acme.review.client.BusinessRiskPythonClient;
import com.acme.review.dto.BusinessRiskCallbackRequest;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.argThat;

class BusinessRiskTaskServiceTest {

    private ReviewTaskMapper reviewTaskMapper;
    private ReviewResultMapper reviewResultMapper;
    private OutboxEventMapper outboxEventMapper;
    private BusinessRiskSseService sseService;
    private SessionMemoryService sessionMemoryService;
    private BusinessRiskTaskService service;

    @BeforeEach
    void setUp() {
        reviewTaskMapper = mock(ReviewTaskMapper.class);
        reviewResultMapper = mock(ReviewResultMapper.class);
        outboxEventMapper = mock(OutboxEventMapper.class);
        sseService = mock(BusinessRiskSseService.class);
        sessionMemoryService = mock(SessionMemoryService.class);
        BusinessRiskPythonClient pythonClient = mock(BusinessRiskPythonClient.class);
        BusinessRiskSourcePreprocessService preprocessService = mock(BusinessRiskSourcePreprocessService.class);
        service = new BusinessRiskTaskService(
                reviewTaskMapper,
                reviewResultMapper,
                outboxEventMapper,
                sseService,
                pythonClient,
                new BusinessRiskMetricsService(new SimpleMeterRegistry()),
                preprocessService,
                sessionMemoryService,
                new ObjectMapper()
        );
    }

    @Test
    void shouldIgnoreRollbackCallbackWhenTaskAlreadyTerminal() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-1");
        task.setStatus(ReviewTaskStatus.SUCCESS);

        when(reviewTaskMapper.findByTaskId("task-1")).thenReturn(Optional.of(task));

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-1");
        callback.setStatus("failed");
        callback.setSuccess(false);

        service.handleCallback(callback);

        verify(reviewTaskMapper, never()).saveOrUpdate(any());
        verify(reviewResultMapper, never()).upsert(any());
        verify(sseService, never()).publish(any(), any(), any(), any());
    }

    @Test
    void shouldIgnoreDuplicateTerminalCallbackWithSameStatus() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-1b");
        task.setStatus(ReviewTaskStatus.SUCCESS);

        when(reviewTaskMapper.findByTaskId("task-1b")).thenReturn(Optional.of(task));

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-1b");
        callback.setStatus("completed");
        callback.setSuccess(true);

        service.handleCallback(callback);

        verify(reviewTaskMapper, never()).saveOrUpdate(any());
        verify(reviewResultMapper, never()).upsert(any());
        verify(sseService, never()).publish(any(), any(), any(), any());
    }

    @Test
    void shouldTransitionProcessingToSuccessAndPublishCompletedEvent() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-2");
        task.setStatus(ReviewTaskStatus.PROCESSING);

        when(reviewTaskMapper.findByTaskId("task-2")).thenReturn(Optional.of(task));
        when(reviewResultMapper.findByTaskId("task-2")).thenReturn(Optional.empty());

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-2");
        callback.setSessionId("session-2");
        callback.setStatus("completed");
        callback.setSuccess(true);
        callback.setRiskSummary("done");

        service.handleCallback(callback);

        assertThat(task.getStatus()).isEqualTo(ReviewTaskStatus.SUCCESS);
        verify(reviewTaskMapper).saveOrUpdate(task);
        verify(reviewResultMapper).upsert(any(ReviewResult.class));
        verify(sseService).publish(
                eq("session-2"),
                eq("task-2"),
                eq("task_completed"),
                argThat(payload -> payload.contains("\"traceId\""))
        );
    }

    @Test
    void shouldTransitionProcessingToHumanReviewAndPublishHumanReviewEvent() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-3");
        task.setStatus(ReviewTaskStatus.PROCESSING);

        when(reviewTaskMapper.findByTaskId("task-3")).thenReturn(Optional.of(task));
        when(reviewResultMapper.findByTaskId("task-3")).thenReturn(Optional.empty());

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-3");
        callback.setSessionId("session-3");
        callback.setStatus("human_review");
        callback.setSuccess(true);

        service.handleCallback(callback);

        assertThat(task.getStatus()).isEqualTo(ReviewTaskStatus.HUMAN_REVIEW);
        verify(reviewTaskMapper).saveOrUpdate(task);
        verify(reviewResultMapper).upsert(any(ReviewResult.class));
        verify(sseService).publish(
                eq("session-3"),
                eq("task-3"),
                eq("task_human_review"),
                argThat(payload -> payload.contains("\"traceId\""))
        );
    }

    @Test
    void shouldIgnoreUnsupportedCallbackStatus() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-4");
        task.setStatus(ReviewTaskStatus.PROCESSING);

        when(reviewTaskMapper.findByTaskId("task-4")).thenReturn(Optional.of(task));

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-4");
        callback.setStatus("processing");

        service.handleCallback(callback);

        verify(reviewTaskMapper, never()).saveOrUpdate(any());
        verify(reviewResultMapper, never()).upsert(any());
        verify(sseService, never()).publish(any(), any(), any(), any());
    }

    @Test
    void shouldIncludeTraceIdInFailedEventPayload() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-6");
        task.setStatus(ReviewTaskStatus.PROCESSING);

        when(reviewTaskMapper.findByTaskId("task-6")).thenReturn(Optional.of(task));
        when(reviewResultMapper.findByTaskId("task-6")).thenReturn(Optional.empty());

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-6");
        callback.setSessionId("session-6");
        callback.setStatus("failed");
        callback.setSuccess(false);
        callback.setTraceId("trace-6");
        callback.setErrorCode("PYTHON_FAILED");
        callback.setErrorMessage("failed");

        service.handleCallback(callback);

        verify(sseService).publish(
                eq("session-6"),
                eq("task-6"),
                eq("task_failed"),
                contains("\"traceId\":\"trace-6\"")
        );
    }

    @Test
    void shouldIgnoreOutOfOrderSuccessAfterFailedTerminal() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-7");
        task.setStatus(ReviewTaskStatus.FAILED);

        when(reviewTaskMapper.findByTaskId("task-7")).thenReturn(Optional.of(task));

        BusinessRiskCallbackRequest callback = new BusinessRiskCallbackRequest();
        callback.setTaskId("task-7");
        callback.setStatus("completed");
        callback.setSuccess(true);

        service.handleCallback(callback);

        verify(reviewTaskMapper, never()).saveOrUpdate(any());
        verify(reviewResultMapper, never()).upsert(any());
        verify(sseService, never()).publish(any(), any(), any(), any());
    }
}
