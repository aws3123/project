package com.acme.review.service;

import com.acme.review.dto.HandoffDecision;
import com.acme.review.dto.HandoffRequest;
import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class ReviewServiceTest {

    private ReviewService reviewService;
    private ReviewTaskMapper reviewTaskRepository;
    private ReviewResultMapper reviewResultRepository;
    private BusinessRiskMetricsService businessRiskMetricsService;

    @BeforeEach
    void setUp() {
        reviewTaskRepository = mock(ReviewTaskMapper.class);
        reviewResultRepository = mock(ReviewResultMapper.class);
        businessRiskMetricsService = mock(BusinessRiskMetricsService.class);
        reviewService = new ReviewService(
                reviewTaskRepository,
                reviewResultRepository,
                businessRiskMetricsService
        );
    }

    @Test
    void shouldSubmitHandoffApprovedAndRecordMetricsForBusinessRiskTask() {
        ReviewTask task = humanReviewTask("task-3", "BUSINESS_RISK_SOURCE");
        Instant createdAt = task.getCreatedAt();
        when(reviewTaskRepository.findByTaskId("task-3")).thenReturn(Optional.of(task));
        when(reviewResultRepository.findByTaskId("task-3")).thenReturn(Optional.empty());

        Optional<TaskDetailResponse> result = reviewService.submitHandoff(
                "task-3",
                handoffRequest(HandoffDecision.APPROVED, "alice", "ok")
        );

        assertThat(result).isPresent();
        assertThat(task.getStatus()).isEqualTo(ReviewTaskStatus.SUCCESS);
        assertThat(task.getHandoffDecision()).isEqualTo("APPROVED");
        assertThat(task.getHandoffOperator()).isEqualTo("alice");
        assertThat(task.getHandoffComment()).isEqualTo("ok");
        assertThat(task.getHandoffHandledAt()).isNotNull();
        assertThat(result.get().getTask().getStatus()).isEqualTo("SUCCESS");
        assertThat(result.get().getTask().getHandoffDecision()).isEqualTo("APPROVED");
        assertThat(result.get().getTask().getHandoffOperator()).isEqualTo("alice");
        assertThat(result.get().getTask().getHandoffComment()).isEqualTo("ok");
        verify(reviewTaskRepository).saveOrUpdate(task);
        verify(businessRiskMetricsService).recordTransition(ReviewTaskStatus.HUMAN_REVIEW, ReviewTaskStatus.SUCCESS);
        verify(businessRiskMetricsService).recordClosed(ReviewTaskStatus.SUCCESS, "handoff");
        verify(businessRiskMetricsService).recordPipelineLatency(createdAt);
    }

    @Test
    void shouldSubmitHandoffRejectedWithoutRecordingMetricsForNonBusinessRiskTask() {
        ReviewTask task = humanReviewTask("task-4", "SYNC");
        when(reviewTaskRepository.findByTaskId("task-4")).thenReturn(Optional.of(task));
        when(reviewResultRepository.findByTaskId("task-4")).thenReturn(Optional.empty());

        Optional<TaskDetailResponse> result = reviewService.submitHandoff(
                "task-4",
                handoffRequest(HandoffDecision.REJECTED, "bob", "manual rejection")
        );

        assertThat(result).isPresent();
        assertThat(task.getStatus()).isEqualTo(ReviewTaskStatus.FAILED);
        assertThat(task.getHandoffDecision()).isEqualTo("REJECTED");
        assertThat(task.getHandoffOperator()).isEqualTo("bob");
        assertThat(task.getHandoffComment()).isEqualTo("manual rejection");
        assertThat(task.getHandoffHandledAt()).isNotNull();
        assertThat(result.get().getTask().getStatus()).isEqualTo("FAILED");
        assertThat(result.get().getTask().getHandoffDecision()).isEqualTo("REJECTED");
        assertThat(result.get().getTask().getHandoffOperator()).isEqualTo("bob");
        assertThat(result.get().getTask().getHandoffComment()).isEqualTo("manual rejection");
        verify(reviewTaskRepository).saveOrUpdate(task);
        verifyNoInteractions(businessRiskMetricsService);
    }

    @Test
    void shouldThrowWhenSubmittingHandoffForNonHumanReviewTask() {
        ReviewTask task = humanReviewTask("task-5", "BUSINESS_RISK_SOURCE");
        task.setStatus(ReviewTaskStatus.SUCCESS);
        when(reviewTaskRepository.findByTaskId("task-5")).thenReturn(Optional.of(task));

        assertThatThrownBy(() -> reviewService.submitHandoff(
                "task-5",
                handoffRequest(HandoffDecision.APPROVED, "alice", "ok")
        ))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("task is not in HUMAN_REVIEW status");

        verify(reviewTaskRepository, never()).saveOrUpdate(any(ReviewTask.class));
        verifyNoInteractions(reviewResultRepository, businessRiskMetricsService);
    }

    @Test
    void shouldThrowWhenDecisionIsChangesRequested() {
        ReviewTask task = humanReviewTask("task-6", "BUSINESS_RISK_SOURCE");
        when(reviewTaskRepository.findByTaskId("task-6")).thenReturn(Optional.of(task));

        assertThatThrownBy(() -> reviewService.submitHandoff(
                "task-6",
                handoffRequest(HandoffDecision.CHANGES_REQUESTED, "carol", "needs more work")
        ))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("CHANGES_REQUESTED is not supported for handoff submission");

        verify(reviewTaskRepository, never()).saveOrUpdate(any(ReviewTask.class));
        verifyNoInteractions(reviewResultRepository, businessRiskMetricsService);
    }

    @Test
    void shouldReturnEmptyWhenTaskDoesNotExistForHandoffSubmission() {
        when(reviewTaskRepository.findByTaskId("missing")).thenReturn(Optional.empty());

        Optional<TaskDetailResponse> result = reviewService.submitHandoff(
                "missing",
                handoffRequest(HandoffDecision.APPROVED, "alice", "ok")
        );

        assertThat(result).isEmpty();
        verify(reviewTaskRepository, never()).saveOrUpdate(any(ReviewTask.class));
        verifyNoInteractions(reviewResultRepository, businessRiskMetricsService);
    }

    private ReviewTask humanReviewTask(String taskId, String mode) {
        ReviewTask task = new ReviewTask();
        task.setTaskId(taskId);
        task.setMode(mode);
        task.setStatus(ReviewTaskStatus.HUMAN_REVIEW);
        task.setCreatedAt(Instant.parse("2026-06-01T00:00:00Z"));
        return task;
    }

    private HandoffRequest handoffRequest(HandoffDecision decision, String operator, String comment) {
        HandoffRequest request = new HandoffRequest();
        request.setDecision(decision);
        request.setOperator(operator);
        request.setComment(comment);
        return request;
    }
}
