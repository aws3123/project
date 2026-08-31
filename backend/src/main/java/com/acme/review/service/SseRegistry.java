package com.acme.review.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Slf4j
@RequiredArgsConstructor
@Component
public class SseRegistry {

    private final ConcurrentHashMap<String, SseEmitter> emitters = new ConcurrentHashMap<>();
    private final ConcurrentMetricsService metrics;

    public SseEmitter register(String taskId) {
        SseEmitter emitter = new SseEmitter(120_000L);
        emitters.put(taskId, emitter);
        metrics.recordSseConnect();
        log.debug("SSE registered taskId={} total={}", taskId, emitters.size());

        emitter.onCompletion(() -> cleanup(taskId));
        emitter.onError(e -> cleanup(taskId));
        emitter.onTimeout(() -> cleanup(taskId));

        // Send initial connection event
        try {
            emitter.send(SseEmitter.event().name("connected").data("{\"taskId\":\"" + taskId + "\"}"));
        } catch (IOException e) {
            cleanup(taskId);
        }

        return emitter;
    }

    public void send(String taskId, String eventName, Object data) {
        SseEmitter emitter = emitters.get(taskId);
        if (emitter == null) {
            return;
        }
        try {
            emitter.send(SseEmitter.event().name(eventName).data(data));
        } catch (IOException e) {
            log.debug("SSE send failed taskId={}, removing", taskId);
            cleanup(taskId);
        }
    }

    public void sendHeartbeat() {
        emitters.forEach((taskId, emitter) -> {
            try {
                emitter.send(SseEmitter.event().comment(""));
            } catch (IOException e) {
                cleanup(taskId);
            }
        });
    }

    public int getActiveCount() {
        return emitters.size();
    }

    private void cleanup(String taskId) {
        SseEmitter removed = emitters.remove(taskId);
        if (removed != null) {
            metrics.recordSseDisconnect();
            try {
                removed.complete();
            } catch (Exception ignored) {
            }
            log.debug("SSE cleanup taskId={} remaining={}", taskId, emitters.size());
        }
    }
}
