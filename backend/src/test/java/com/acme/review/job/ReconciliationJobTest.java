package com.acme.review.job;

import com.acme.review.config.OrchestratorProperties;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.entity.TaskAuditLog;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.ReviewTaskPayloadMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReconciliationJobTest {

    private ReviewTaskMapper taskRepo;
    private OutboxEventMapper outboxMapper;
    private ReviewResultMapper resultRepo;
    private TaskAuditLogMapper auditLogMapper;
    private ReviewTaskPayloadMapper payloadMapper;
    private ReconciliationJob job;

    @BeforeEach
    void setUp() {
        taskRepo = mock(ReviewTaskMapper.class);
        outboxMapper = mock(OutboxEventMapper.class);
        resultRepo = mock(ReviewResultMapper.class);
        auditLogMapper = mock(TaskAuditLogMapper.class);
        payloadMapper = mock(ReviewTaskPayloadMapper.class);

        OrchestratorProperties orchProps = new OrchestratorProperties(4, 16, 200, 60, 5000, 60000);
        job = new ReconciliationJob(taskRepo, outboxMapper, resultRepo, auditLogMapper, payloadMapper, orchProps, new ObjectMapper());
    }

    @Test
    void shouldMarkBusinessRiskPendingTaskFailedWhenOutboxMissing() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-br-1");
        task.setStatus(ReviewTaskStatus.PENDING);
        task.setMode("BUSINESS_RISK_SOURCE");
        task.setCreatedAt(Instant.now().minusSeconds(3600));

        when(taskRepo.selectList(any())).thenReturn(List.of(task));
        when(outboxMapper.selectCount(any())).thenReturn(0L);

        job.reconcileStuckPending();

        verify(taskRepo).updateById(task);
        verify(resultRepo).upsert(any());
        verify(outboxMapper, never()).insert(any(OutboxEvent.class));
        verify(auditLogMapper).insert(any(TaskAuditLog.class));
    }

    @Test
    void shouldRebuildOutboxForNonBusinessRiskPendingTask() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-sync-1");
        task.setStatus(ReviewTaskStatus.PENDING);
        task.setMode("ASYNC");
        task.setCreatedAt(Instant.now().minusSeconds(3600));

        when(taskRepo.selectList(any())).thenReturn(List.of(task));
        when(outboxMapper.selectCount(any())).thenReturn(0L);

        job.reconcileStuckPending();

        verify(outboxMapper).insert(any(OutboxEvent.class));
        verify(taskRepo, never()).updateById(eq(task));
    }
}
