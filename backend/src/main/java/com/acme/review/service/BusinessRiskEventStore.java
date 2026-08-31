package com.acme.review.service;

import com.acme.review.dto.SseBusinessRiskEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ObjectRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
@Slf4j
public class BusinessRiskEventStore {

    private final ObjectMapper objectMapper;
    private final BusinessRiskMetricsService metricsService;

    @Autowired(required = false)
    private StringRedisTemplate redisTemplate;

    @Value("${business-risk.sse.replay-limit:1000}")
    private int replayLimit;

    @Value("${business-risk.sse.ttl-seconds:3600}")
    private long ttlSeconds;

    @Value("${business-risk.sse.max-total-events:50000}")
    private int maxTotalEvents;

    @Value("${business-risk.sse.max-events-per-session:5000}")
    private int maxEventsPerSession;

    @Value("${business-risk.sse.max-events-per-task:500}")
    private int maxEventsPerTask;

    @Value("${business-risk.sse.persistence-backend:memory}")
    private String persistenceBackend;

    @Value("${business-risk.sse.redis-key-prefix:bizrisk:sse:}")
    private String redisKeyPrefix;

    private final Object lock = new Object();
    private final Map<String, Deque<StoredEvent>> sessionEvents = new HashMap<>();
    private final Map<String, Map<String, Integer>> sessionTaskCounts = new HashMap<>();
    private final Deque<EventPointer> globalOrder = new LinkedList<>();
    private int totalEventCount;

    public void append(SseBusinessRiskEvent event) {
        long now = System.currentTimeMillis();
        synchronized (lock) {
            evictExpiredLocked(now);

            Deque<StoredEvent> events = sessionEvents.computeIfAbsent(event.getSessionId(), key -> new LinkedList<>());
            events.addLast(new StoredEvent(event, now));
            globalOrder.addLast(new EventPointer(event.getSessionId(), event.getEventId()));
            totalEventCount += 1;

            incrementTaskCount(event.getSessionId(), normalizeTaskId(event.getTaskId()));
            trimTaskEventsLocked(event.getSessionId(), normalizeTaskId(event.getTaskId()));
            trimSessionEventsLocked(event.getSessionId());
            trimGlobalEventsLocked();
        }

        appendRedisIfEnabled(event);
    }

    public List<SseBusinessRiskEvent> replayFrom(String sessionId, String lastEventId) {
        List<SseBusinessRiskEvent> redisEvents = replayFromRedisIfEnabled(sessionId, lastEventId);
        if (!redisEvents.isEmpty()) {
            return recordReplayOutcome(redisEvents, lastEventId);
        }

        synchronized (lock) {
            evictExpiredLocked(System.currentTimeMillis());
            Deque<StoredEvent> events = sessionEvents.get(sessionId);
            if (events == null || events.isEmpty()) {
                return recordReplayOutcome(List.of(), lastEventId);
            }

            List<SseBusinessRiskEvent> snapshot = new ArrayList<>(events.size());
            for (StoredEvent event : events) {
                snapshot.add(event.event());
            }
            return recordReplayOutcome(applyReplayWindow(snapshot, lastEventId), lastEventId);
        }
    }

    private void trimTaskEventsLocked(String sessionId, String taskId) {
        if (maxEventsPerTask <= 0) {
            return;
        }

        int count = getTaskCount(sessionId, taskId);
        if (count <= maxEventsPerTask) {
            return;
        }

        Deque<StoredEvent> events = sessionEvents.get(sessionId);
        if (events == null || events.isEmpty()) {
            return;
        }

        while (count > maxEventsPerTask) {
            boolean removed = removeFirstTaskEvent(events, sessionId, taskId);
            if (!removed) {
                break;
            }
            count = getTaskCount(sessionId, taskId);
        }
    }

    private boolean removeFirstTaskEvent(Deque<StoredEvent> events, String sessionId, String taskId) {
        Iterator<StoredEvent> iterator = events.iterator();
        while (iterator.hasNext()) {
            StoredEvent current = iterator.next();
            if (taskId.equals(normalizeTaskId(current.event().getTaskId()))) {
                iterator.remove();
                onEventRemovedLocked(sessionId, current.event());
                return true;
            }
        }
        return false;
    }

    private void trimSessionEventsLocked(String sessionId) {
        if (maxEventsPerSession <= 0) {
            return;
        }

        Deque<StoredEvent> events = sessionEvents.get(sessionId);
        if (events == null) {
            return;
        }

        while (events.size() > maxEventsPerSession) {
            StoredEvent removed = events.pollFirst();
            if (removed == null) {
                break;
            }
            onEventRemovedLocked(sessionId, removed.event());
        }

        if (events.isEmpty()) {
            sessionEvents.remove(sessionId);
            sessionTaskCounts.remove(sessionId);
        }
    }

    private void trimGlobalEventsLocked() {
        if (maxTotalEvents <= 0) {
            return;
        }

        while (totalEventCount > maxTotalEvents) {
            EventPointer pointer = globalOrder.pollFirst();
            if (pointer == null) {
                break;
            }

            Deque<StoredEvent> events = sessionEvents.get(pointer.sessionId());
            if (events == null || events.isEmpty()) {
                continue;
            }

            boolean removed = removeByEventId(events, pointer.sessionId(), pointer.eventId());
            if (removed && events.isEmpty()) {
                sessionEvents.remove(pointer.sessionId());
                sessionTaskCounts.remove(pointer.sessionId());
            }
        }
    }

    private boolean removeByEventId(Deque<StoredEvent> events, String sessionId, String eventId) {
        Iterator<StoredEvent> iterator = events.iterator();
        while (iterator.hasNext()) {
            StoredEvent current = iterator.next();
            if (eventId.equals(current.event().getEventId())) {
                iterator.remove();
                onEventRemovedLocked(sessionId, current.event());
                return true;
            }
        }
        return false;
    }

    private void evictExpiredLocked(long nowMillis) {
        if (ttlSeconds <= 0) {
            return;
        }

        long expireBefore = nowMillis - Duration.ofSeconds(ttlSeconds).toMillis();
        Iterator<Map.Entry<String, Deque<StoredEvent>>> sessionIterator = sessionEvents.entrySet().iterator();
        while (sessionIterator.hasNext()) {
            Map.Entry<String, Deque<StoredEvent>> entry = sessionIterator.next();
            String sessionId = entry.getKey();
            Deque<StoredEvent> events = entry.getValue();

            while (!events.isEmpty()) {
                StoredEvent first = events.peekFirst();
                if (first == null || first.timestampMillis() > expireBefore) {
                    break;
                }
                events.pollFirst();
                onEventRemovedLocked(sessionId, first.event());
            }

            if (events.isEmpty()) {
                sessionIterator.remove();
                sessionTaskCounts.remove(sessionId);
            }
        }
    }

    private void onEventRemovedLocked(String sessionId, SseBusinessRiskEvent event) {
        totalEventCount = Math.max(0, totalEventCount - 1);
        decrementTaskCount(sessionId, normalizeTaskId(event.getTaskId()));
        removeEventPointerLocked(sessionId, event.getEventId());
    }

    private void removeEventPointerLocked(String sessionId, String eventId) {
        Iterator<EventPointer> iterator = globalOrder.iterator();
        while (iterator.hasNext()) {
            EventPointer pointer = iterator.next();
            if (sessionId.equals(pointer.sessionId()) && eventId.equals(pointer.eventId())) {
                iterator.remove();
                return;
            }
        }
    }

    private void incrementTaskCount(String sessionId, String taskId) {
        Map<String, Integer> taskCounts = sessionTaskCounts.computeIfAbsent(sessionId, key -> new HashMap<>());
        taskCounts.put(taskId, taskCounts.getOrDefault(taskId, 0) + 1);
    }

    private void decrementTaskCount(String sessionId, String taskId) {
        Map<String, Integer> taskCounts = sessionTaskCounts.get(sessionId);
        if (taskCounts == null) {
            return;
        }

        Integer current = taskCounts.get(taskId);
        if (current == null) {
            return;
        }

        if (current <= 1) {
            taskCounts.remove(taskId);
        } else {
            taskCounts.put(taskId, current - 1);
        }

        if (taskCounts.isEmpty()) {
            sessionTaskCounts.remove(sessionId);
        }
    }

    private int getTaskCount(String sessionId, String taskId) {
        Map<String, Integer> taskCounts = sessionTaskCounts.get(sessionId);
        if (taskCounts == null) {
            return 0;
        }
        return taskCounts.getOrDefault(taskId, 0);
    }

    private String normalizeTaskId(String taskId) {
        return taskId == null || taskId.isBlank() ? "_" : taskId;
    }

    private List<SseBusinessRiskEvent> applyReplayWindow(List<SseBusinessRiskEvent> events, String lastEventId) {
        if (events.isEmpty()) {
            return List.of();
        }

        int startIndex = 0;
        if (lastEventId != null && !lastEventId.isBlank()) {
            int index = -1;
            for (int i = 0; i < events.size(); i++) {
                if (lastEventId.equals(events.get(i).getEventId())) {
                    index = i;
                    break;
                }
            }
            if (index >= 0) {
                startIndex = index + 1;
            }
        }

        List<SseBusinessRiskEvent> replay = new ArrayList<>(events.subList(Math.min(startIndex, events.size()), events.size()));

        if (replayLimit > 0 && replay.size() > replayLimit) {
            return new ArrayList<>(replay.subList(replay.size() - replayLimit, replay.size()));
        }
        return replay;
    }

    private List<SseBusinessRiskEvent> recordReplayOutcome(List<SseBusinessRiskEvent> replay, String lastEventId) {
        String outcome;
        if (lastEventId == null || lastEventId.isBlank()) {
            outcome = "no_anchor";
        } else if (replay.isEmpty()) {
            outcome = "miss";
        } else {
            outcome = "hit";
        }
        metricsService.recordReplay(outcome, replay.size());
        return replay;
    }

    private boolean useRedis() {
        return "redis".equalsIgnoreCase(persistenceBackend) && redisTemplate != null;
    }

    private void appendRedisIfEnabled(SseBusinessRiskEvent event) {
        if (!useRedis()) {
            return;
        }

        try {
            String key = redisSessionKey(event.getSessionId());
            String payload = objectMapper.writeValueAsString(event);
            RecordId recordId = redisTemplate.opsForStream().add(ObjectRecord.create(key, payload));
            if (recordId != null && maxEventsPerSession > 0) {
                redisTemplate.opsForStream().trim(key, maxEventsPerSession);
            }
            if (ttlSeconds > 0) {
                redisTemplate.expire(key, Duration.ofSeconds(ttlSeconds));
            }
        } catch (Exception ex) {
            log.warn("append redis sse event failed sessionId={} eventId={}", event.getSessionId(), event.getEventId(), ex);
        }
    }

    private List<SseBusinessRiskEvent> replayFromRedisIfEnabled(String sessionId, String lastEventId) {
        if (!useRedis()) {
            return List.of();
        }

        try {
            String key = redisSessionKey(sessionId);
            List<MapRecord<String, Object, Object>> records = redisTemplate.opsForStream()
                    .range(key, Range.unbounded());
            if (records == null || records.isEmpty()) {
                return List.of();
            }

            List<SseBusinessRiskEvent> events = new ArrayList<>(records.size());
            for (MapRecord<String, Object, Object> record : records) {
                Object payload = record.getValue().get("payload");
                if (!(payload instanceof String value) || value.isBlank()) {
                    continue;
                }
                events.add(objectMapper.readValue(value, SseBusinessRiskEvent.class));
            }
            return applyReplayWindow(events, lastEventId);
        } catch (Exception ex) {
            log.warn("replay redis sse event failed sessionId={}, fallback memory", sessionId, ex);
            return List.of();
        }
    }

    private String redisSessionKey(String sessionId) {
        return redisKeyPrefix + sessionId;
    }

    private record StoredEvent(SseBusinessRiskEvent event, long timestampMillis) {
    }

    private record EventPointer(String sessionId, String eventId) {
    }
}
