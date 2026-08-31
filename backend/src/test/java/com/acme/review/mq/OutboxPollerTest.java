package com.acme.review.mq;

import com.acme.review.dto.BusinessRiskPythonSourceResponse;
import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.exception.PythonHttpException;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.service.BusinessRiskMetricsService;
import com.acme.review.service.BusinessRiskTaskService;
import com.acme.review.service.BusinessRiskWorkerRegistryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.cloud.stream.function.StreamBridge;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OutboxPollerTest {

    private OutboxEventMapper outboxMapper;
    private BusinessRiskTaskService businessRiskTaskService;
    private BusinessRiskWorkerRegistryService workerRegistryService;
    private OutboxPoller poller;

    @BeforeEach
    void setUp() {
        outboxMapper = mock(OutboxEventMapper.class);
        StreamBridge streamBridge = mock(StreamBridge.class);
        businessRiskTaskService = mock(BusinessRiskTaskService.class);
        workerRegistryService = mock(BusinessRiskWorkerRegistryService.class);
        BusinessRiskMetricsService metricsService = new BusinessRiskMetricsService(new SimpleMeterRegistry());
        poller = new OutboxPoller(outboxMapper, streamBridge, new ObjectMapper(), businessRiskTaskService, workerRegistryService, metricsService);
    }

    @Test
    void shouldSendBusinessRiskDispatchAndMarkSent() {
        OutboxEvent event = new OutboxEvent();
        event.setEventId("e1");
        event.setAggregateId("task-1");
        event.setEventType("BUSINESS_RISK_DISPATCH");
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setPayload("{\"task_id\":\"task-1\",\"session_id\":\"session-1\",\"trace_id\":\"trace-1\",\"schema_version\":\"2.0\",\"java_preprocess_version\":\"3.0\"}");

        when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(allowedSnapshot());

        BusinessRiskPythonSourceResponse response = new BusinessRiskPythonSourceResponse();
        response.setTaskId("task-1");
        response.setStatus("completed");
        when(businessRiskTaskService.analyzeSource(any())).thenReturn(response);

        poller.sendEvent(event);

        verify(businessRiskTaskService).handlePythonSourceResponse(eq("task-1"), eq("session-1"), eq("trace-1"), eq(response));
        verify(outboxMapper).updateById(event);
        assertThat(event.getStatus()).isEqualTo("SENT");
    }

    @Test
    void shouldBlockBusinessRiskDispatchWhenNoCompatibleWorkersExist() {
        OutboxEvent event = new OutboxEvent();
        event.setEventId("e-block-1");
        event.setAggregateId("task-block-1");
        event.setEventType("BUSINESS_RISK_DISPATCH");
        event.setStatus("PENDING");
        event.setRetryCount(9);
        event.setPayload("{\"task_id\":\"task-block-1\",\"session_id\":\"session-task-block-1\",\"trace_id\":\"trace-block-1\",\"schema_version\":\"2.0\",\"java_preprocess_version\":\"3.0\"}");

        when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(blockedSnapshot("PYTHON_WORKER_UNAVAILABLE"));

        poller.sendEvent(event);

        verify(businessRiskTaskService).markBusinessRiskDispatchFailed(
                "task-block-1",
                "session-task-block-1",
                "trace-block-1",
                "PYTHON_WORKER_UNAVAILABLE",
                "Business risk dispatch blocked: PYTHON_WORKER_UNAVAILABLE"
        );
        verify(outboxMapper).updateById(event);
        assertThat(event.getStatus()).isEqualTo("DEAD");
    }

    @Test
    void shouldMarkBusinessRiskEventDeadOnNonRetryableHttp() {
        OutboxEvent event = new OutboxEvent();
        event.setEventId("e2");
        event.setAggregateId("task-2");
        event.setEventType("BUSINESS_RISK_DISPATCH");
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setCreatedAt(Instant.now());
        event.setPayload("{\"task_id\":\"task-2\",\"session_id\":\"session-2\",\"trace_id\":\"trace-2\",\"schema_version\":\"2.0\",\"java_preprocess_version\":\"3.0\"}");

        when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(allowedSnapshot());
        when(businessRiskTaskService.analyzeSource(any()))
                .thenThrow(new PythonHttpException("bad request", 400, false));

        poller.sendEvent(event);

        verify(businessRiskTaskService).markBusinessRiskDispatchFailed(
                eq("task-2"),
                eq("session-2"),
                eq("trace-2"),
                eq("PYTHON_DISPATCH_FAILED"),
                eq("bad request")
        );
        verify(outboxMapper).updateById(event);
        verify(businessRiskTaskService, never()).handlePythonSourceResponse(any(), any(), any(), any());
        assertThat(event.getStatus()).isEqualTo("DEAD");
    }

    @Test
    void shouldFallbackTraceIdToAggregateIdWhenMissingInPayload() {
        OutboxEvent event = new OutboxEvent();
        event.setEventId("e3");
        event.setAggregateId("task-3");
        event.setEventType("BUSINESS_RISK_DISPATCH");
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setPayload("{\"task_id\":\"task-3\",\"session_id\":\"session-3\",\"schema_version\":\"2.0\",\"java_preprocess_version\":\"3.0\"}");

        when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(allowedSnapshot());

        BusinessRiskPythonSourceResponse response = new BusinessRiskPythonSourceResponse();
        response.setTaskId("task-3");
        response.setStatus("completed");
        when(businessRiskTaskService.analyzeSource(any())).thenReturn(response);

        poller.sendEvent(event);

        ArgumentCaptor<com.acme.review.dto.BusinessRiskPythonSourceRequest> requestCaptor = ArgumentCaptor.forClass(com.acme.review.dto.BusinessRiskPythonSourceRequest.class);
        verify(businessRiskTaskService).analyzeSource(requestCaptor.capture());
        assertThat(requestCaptor.getValue().getTraceId()).isEqualTo("task-3");
        verify(businessRiskTaskService).handlePythonSourceResponse(eq("task-3"), eq("session-3"), eq("task-3"), eq(response));
    }

    @Test
    void shouldReadBusinessRiskDispatchPayloadWrappedAsJsonString() {
        OutboxEvent event = new OutboxEvent();
        event.setEventId("e4");
        event.setAggregateId("task-4");
        event.setEventType("BUSINESS_RISK_DISPATCH");
        event.setStatus("PENDING");
        event.setRetryCount(0);
        event.setPayload("\"{\\\"task_id\\\":\\\"task-4\\\",\\\"session_id\\\":\\\"session-4\\\",\\\"trace_id\\\":\\\"trace-4\\\",\\\"schema_version\\\":\\\"2.0\\\",\\\"java_preprocess_version\\\":\\\"3.0\\\"}\"");

        when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(allowedSnapshot());

        BusinessRiskPythonSourceResponse response = new BusinessRiskPythonSourceResponse();
        response.setTaskId("task-4");
        response.setStatus("completed");
        when(businessRiskTaskService.analyzeSource(any())).thenReturn(response);

        poller.sendEvent(event);

        verify(businessRiskTaskService).handlePythonSourceResponse(eq("task-4"), eq("session-4"), eq("trace-4"), eq(response));
        verify(outboxMapper).updateById(event);
        assertThat(event.getStatus()).isEqualTo("SENT");
    }

    private BusinessRiskWorkerRegistrySnapshot allowedSnapshot() {
        BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();
        snapshot.setActiveWorkers(1);
        snapshot.setReadyWorkers(1);
        snapshot.setAvailableSlots(2);
        snapshot.setDispatchAllowed(true);
        return snapshot;
    }

    private BusinessRiskWorkerRegistrySnapshot blockedSnapshot(String reason) {
        BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();
        snapshot.setActiveWorkers(0);
        snapshot.setReadyWorkers(0);
        snapshot.setAvailableSlots(0);
        snapshot.setDispatchAllowed(false);
        snapshot.setBlockReason(reason);
        return snapshot;
    }
}
