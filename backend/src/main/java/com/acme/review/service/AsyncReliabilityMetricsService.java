package com.acme.review.service;

import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.concurrent.atomic.AtomicLong;

/** Exposes DB-backed backlog gauges used by resilience tests and dashboards. */
@Service
public class AsyncReliabilityMetricsService {

    private final OutboxEventMapper outboxMapper;
    private final ReviewTaskMapper taskMapper;
    private final AtomicLong outboxPending = new AtomicLong();
    private final AtomicLong tasksInflight = new AtomicLong();
    private final AtomicLong tasksFailed = new AtomicLong();

    public AsyncReliabilityMetricsService(OutboxEventMapper outboxMapper,
                                          ReviewTaskMapper taskMapper,
                                          MeterRegistry registry) {
        this.outboxMapper = outboxMapper;
        this.taskMapper = taskMapper;
        Gauge.builder("review.outbox.pending", outboxPending, AtomicLong::get)
                .description("Outbox events awaiting Kafka publication").register(registry);
        Gauge.builder("review.tasks.inflight", tasksInflight, AtomicLong::get)
                .description("Async tasks in pending or processing state").register(registry);
        Gauge.builder("review.tasks.failed.current", tasksFailed, AtomicLong::get)
                .description("Async tasks currently in failed state").register(registry);
    }

    @Scheduled(fixedDelayString = "${review.metrics.snapshot-interval-ms:15000}")
    public void refresh() {
        outboxPending.set(outboxMapper.selectCount(new LambdaQueryWrapper<OutboxEvent>()
                .eq(OutboxEvent::getStatus, "PENDING")));
        tasksInflight.set(taskMapper.selectCount(new LambdaQueryWrapper<ReviewTask>()
                .in(ReviewTask::getStatus, ReviewTaskStatus.PENDING, ReviewTaskStatus.PROCESSING)));
        tasksFailed.set(taskMapper.selectCount(new LambdaQueryWrapper<ReviewTask>()
                .eq(ReviewTask::getStatus, ReviewTaskStatus.FAILED)));
    }
}
