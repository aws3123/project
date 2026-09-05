package com.acme.review.service;

import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FeedbackServiceTest {

    private FeedbackMapper feedbackMapper;
    private OutboxEventMapper outboxMapper;
    private FeedbackService service;

    @BeforeEach
    void setUp() {
        feedbackMapper = mock(FeedbackMapper.class);
        outboxMapper = mock(OutboxEventMapper.class);
        service = new FeedbackService(feedbackMapper, outboxMapper, new ObjectMapper());
    }

    @Test
    void shouldInsertNewFeedback() {
        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_down");

        when(feedbackMapper.selectList(any())).thenReturn(List.of());
        when(feedbackMapper.insert(any(UserFeedback.class))).thenReturn(1);

        UserFeedback saved = service.submit(feedback);

        assertThat(saved.getTaskId()).isEqualTo("task-1");
        assertThat(saved.getFeedbackType()).isEqualTo("thumbs_down");
        verify(feedbackMapper).insert(any(UserFeedback.class));
    }

    @Test
    void shouldQueueOutboxEventForThumbsDown() {
        UserFeedback feedback = new UserFeedback();
        feedback.setId(9L);
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_down");
        feedback.setCategory("误报");
        feedback.setTraceId("trace-abc");

        when(feedbackMapper.selectList(any())).thenReturn(List.of());
        when(feedbackMapper.insert(any(UserFeedback.class))).thenReturn(1);

        service.submit(feedback);

        ArgumentCaptor<OutboxEvent> captor = ArgumentCaptor.forClass(OutboxEvent.class);
        verify(outboxMapper).insert(captor.capture());
        OutboxEvent event = captor.getValue();
        assertThat(event.getEventType()).isEqualTo("FEEDBACK_NEGATIVE");
        assertThat(event.getAggregateType()).isEqualTo("user_feedback");
        assertThat(event.getAggregateId()).isEqualTo("task-1");
        assertThat(event.getStatus()).isEqualTo("PENDING");
        assertThat(event.getPayload()).contains("task-1").contains("误报").contains("trace-abc").contains("messageId");
    }

    @Test
    void shouldNotQueueOutboxEventForThumbsUp() {
        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_up");

        when(feedbackMapper.selectList(any())).thenReturn(List.of());

        service.submit(feedback);

        verify(outboxMapper, never()).insert(any(OutboxEvent.class));
    }

    @Test
    void shouldUpdateExistingFeedbackForSameTaskAndSession() {
        UserFeedback existing = new UserFeedback();
        existing.setId(1L);
        existing.setTaskId("task-1");
        existing.setSessionId("session-1");
        existing.setFeedbackType("thumbs_up");

        UserFeedback newFeedback = new UserFeedback();
        newFeedback.setTaskId("task-1");
        newFeedback.setSessionId("session-1");
        newFeedback.setFeedbackType("thumbs_up");
        newFeedback.setCategory("误报");

        when(feedbackMapper.selectList(any())).thenReturn(List.of(existing));

        UserFeedback saved = service.submit(newFeedback);

        assertThat(saved.getId()).isEqualTo(1L);
        assertThat(saved.getCategory()).isEqualTo("误报");
        verify(feedbackMapper).updateById(any(UserFeedback.class));
        verify(feedbackMapper, never()).insert(any(UserFeedback.class));
    }

    @Test
    void shouldTruncateOversizedMetadata() {
        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_up");
        feedback.setMetadata("x".repeat(70000));

        when(feedbackMapper.selectList(any())).thenReturn(List.of());

        service.submit(feedback);

        assertThat(feedback.getMetadata().length()).isLessThanOrEqualTo(65535);
    }

    @Test
    void shouldGetStats() {
        Instant from = Instant.parse("2026-06-01T00:00:00Z");
        Instant to = Instant.parse("2026-06-27T00:00:00Z");

        when(feedbackMapper.countByType(eq(from), eq(to), eq(null)))
                .thenReturn(List.of(
                        Map.of("feedback_type", "thumbs_up", "cnt", 30L),
                        Map.of("feedback_type", "thumbs_down", "cnt", 10L)
                ));
        when(feedbackMapper.dailyBreakdown(eq(from), eq(to), eq(null)))
                .thenReturn(List.of(
                        Map.of("day", "2026-06-01", "feedback_type", "thumbs_up", "cnt", 5L),
                        Map.of("day", "2026-06-01", "feedback_type", "thumbs_down", "cnt", 2L)
                ));

        Map<String, Object> stats = service.getStats(from, to, null);

        assertThat(stats.get("total")).isEqualTo(40L);
        assertThat(stats.get("thumbs_up")).isEqualTo(30L);
        assertThat(stats.get("thumbs_down")).isEqualTo(10L);
        assertThat(stats.get("ratio")).isEqualTo("0.75");
        assertThat(stats.get("daily_breakdown")).isInstanceOf(List.class);
    }

    @Test
    void shouldExportFeedback() {
        Instant from = Instant.parse("2026-06-01T00:00:00Z");
        Instant to = Instant.parse("2026-06-27T00:00:00Z");

        Page<UserFeedback> mockPage = new Page<>(1, 10);
        UserFeedback fb = new UserFeedback();
        fb.setId(1L);
        fb.setTaskId("task-1");
        fb.setFeedbackType("thumbs_up");
        mockPage.setRecords(List.of(fb));
        mockPage.setTotal(1);

        when(feedbackMapper.selectPage(any(Page.class), any())).thenReturn(mockPage);

        IPage<UserFeedback> result = service.export(from, to, "review", 1, 10);
        assertThat(result.getRecords()).hasSize(1);
        assertThat(result.getRecords().get(0).getTaskId()).isEqualTo("task-1");
    }
}
