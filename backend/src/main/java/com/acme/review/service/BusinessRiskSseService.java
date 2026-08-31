package com.acme.review.service;

import com.acme.review.dto.SseBusinessRiskEvent;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class BusinessRiskSseService {

    private final BusinessRiskEventStore eventStore;
    private final BusinessRiskMetricsService metricsService;
    private final Sinks.Many<SseBusinessRiskEvent> sink = Sinks.many().multicast().onBackpressureBuffer();

    @Value("${business-risk.sse.heartbeat-seconds:25}")
    private long heartbeatSeconds;

    public void publish(String sessionId, String taskId, String type, String payload) {
        SseBusinessRiskEvent event = nextEvent(sessionId, taskId, type, payload);
        eventStore.append(event);
        sink.tryEmitNext(event);
    }

    public Flux<SseBusinessRiskEvent> replayFrom(String sessionId, String lastEventId) {
        List<SseBusinessRiskEvent> replay = eventStore.replayFrom(sessionId, lastEventId);
        return Flux.fromIterable(replay);
    }

    public Flux<SseBusinessRiskEvent> liveStream(String sessionId) {
        Flux<SseBusinessRiskEvent> live = sink.asFlux().filter(event -> sessionId.equals(event.getSessionId()));
        Flux<SseBusinessRiskEvent> heartbeat = Flux.interval(Duration.ofSeconds(Math.max(1L, heartbeatSeconds)))
                .map(tick -> nextEvent(sessionId, "", "heartbeat", "{\"status\":\"HEARTBEAT\"}"));
        return Flux.merge(live, heartbeat)
                .doOnSubscribe(subscription -> metricsService.recordStreamOpened())
                .doFinally(signalType -> metricsService.recordStreamClosed());
    }

    private SseBusinessRiskEvent nextEvent(String sessionId, String taskId, String type, String payload) {
        String eventId = Instant.now().toEpochMilli() + "-" + UUID.randomUUID();
        return new SseBusinessRiskEvent(eventId, sessionId, taskId, type, payload);
    }
}
