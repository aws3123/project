package com.acme.review.service;

import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.acme.review.entity.ReviewTaskStatus;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class BusinessRiskMetricsService {

    private final MeterRegistry meterRegistry;
    private final Timer pipelineLatencyTimer;
    private final DistributionSummary replayEventSummary;
    private final Counter createdCounter;
    private final Counter streamOpenCounter;
    private final AtomicInteger activeStreamCount;
    private final AtomicInteger activeWorkerCount;
    private final AtomicInteger readyWorkerCount;
    private final AtomicInteger availableSlotCount;
    private final AtomicLong latestPreparedBytes;
    private final AtomicLong latestRawBytes;

    public BusinessRiskMetricsService(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
        this.createdCounter = Counter.builder("business_risk.task.created")
                .description("Created business risk tasks")
                .register(meterRegistry);
        this.pipelineLatencyTimer = Timer.builder("business_risk.pipeline.latency")
                .description("End-to-end business risk pipeline latency")
                .publishPercentiles(0.5, 0.9, 0.95, 0.99)
                .register(meterRegistry);
        this.replayEventSummary = DistributionSummary.builder("business_risk.replay.events")
                .description("Number of events returned in business risk replay windows")
                .register(meterRegistry);
        this.streamOpenCounter = Counter.builder("business_risk.sse.stream.open")
                .description("Opened business risk SSE streams")
                .register(meterRegistry);
        this.activeStreamCount = meterRegistry.gauge("business_risk.sse.active_streams", new AtomicInteger(0));
        this.activeWorkerCount = meterRegistry.gauge("business_risk.worker.active", new AtomicInteger(0));
        this.readyWorkerCount = meterRegistry.gauge("business_risk.worker.ready", new AtomicInteger(0));
        this.availableSlotCount = meterRegistry.gauge("business_risk.worker.available_slots", new AtomicInteger(0));
        this.latestPreparedBytes = meterRegistry.gauge("business_risk.preprocess.prepared_bytes", new AtomicLong(0));
        this.latestRawBytes = meterRegistry.gauge("business_risk.preprocess.raw_bytes", new AtomicLong(0));
    }

    public void recordCreated() {
        createdCounter.increment();
    }

    public void recordTransition(ReviewTaskStatus from, ReviewTaskStatus to) {
        Counter.builder("business_risk.task.transition")
                .description("Business risk task status transitions")
                .tag("from", tagValue(from))
                .tag("to", tagValue(to))
                .register(meterRegistry)
                .increment();
    }

    public void recordClosed(ReviewTaskStatus status, String source) {
        Counter.builder("business_risk.task.closed")
                .description("Business risk tasks that reached a closed outcome")
                .tag("status", tagValue(status))
                .tag("source", tagValue(source))
                .register(meterRegistry)
                .increment();
    }

    public void recordPipelineLatency(Instant createdAt) {
        if (createdAt == null) {
            return;
        }
        Duration duration = Duration.between(createdAt, Instant.now());
        if (!duration.isNegative()) {
            pipelineLatencyTimer.record(duration);
        }
    }

    public void recordReplay(String outcome, int eventCount) {
        Counter.builder("business_risk.replay.request")
                .description("Business risk replay requests by outcome")
                .tag("outcome", tagValue(outcome))
                .register(meterRegistry)
                .increment();
        replayEventSummary.record(Math.max(0, eventCount));
    }

    public void recordStreamOpened() {
        streamOpenCounter.increment();
        activeStreamCount.incrementAndGet();
    }

    public void recordStreamClosed() {
        activeStreamCount.updateAndGet(current -> Math.max(0, current - 1));
    }

    public void recordPreprocess(long rawBytes, long preparedBytes, String decision) {
        latestRawBytes.set(Math.max(0, rawBytes));
        latestPreparedBytes.set(Math.max(0, preparedBytes));
        Counter.builder("business_risk.preprocess.total")
                .tag("decision", tagValue(decision))
                .register(meterRegistry)
                .increment();
    }

    public void recordPreprocessFailure(String errorCode) {
        Counter.builder("business_risk.preprocess.failed")
                .tag("errorCode", tagValue(errorCode))
                .register(meterRegistry)
                .increment();
    }

    public void recordDispatchBlocked(String reason) {
        Counter.builder("business_risk.dispatch.blocked")
                .tag("reason", tagValue(reason))
                .register(meterRegistry)
                .increment();
    }

    public void recordDispatchAttempt(String outcome) {
        Counter.builder("business_risk.dispatch.attempt")
                .tag("outcome", tagValue(outcome))
                .register(meterRegistry)
                .increment();
    }

    public void recordWorkerSnapshot(BusinessRiskWorkerRegistrySnapshot snapshot) {
        if (snapshot == null) {
            return;
        }
        activeWorkerCount.set(snapshot.getActiveWorkers());
        readyWorkerCount.set(snapshot.getReadyWorkers());
        availableSlotCount.set(snapshot.getAvailableSlots());
    }

    private String tagValue(Object value) {
        return value == null ? "UNKNOWN" : value.toString();
    }
}
