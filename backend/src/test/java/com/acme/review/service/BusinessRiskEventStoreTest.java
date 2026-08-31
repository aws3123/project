package com.acme.review.service;

import com.acme.review.dto.SseBusinessRiskEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.lang.reflect.Field;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class BusinessRiskEventStoreTest {

    private BusinessRiskEventStore eventStore;

    @BeforeEach
    void setUp() throws Exception {
        eventStore = new BusinessRiskEventStore(new ObjectMapper(), new BusinessRiskMetricsService(new SimpleMeterRegistry()));
        setField(eventStore, "replayLimit", 1000);
        setField(eventStore, "ttlSeconds", 3600L);
        setField(eventStore, "maxTotalEvents", 1000);
        setField(eventStore, "maxEventsPerSession", 1000);
        setField(eventStore, "maxEventsPerTask", 1000);
        setField(eventStore, "persistenceBackend", "memory");
        setField(eventStore, "redisKeyPrefix", "bizrisk:sse:");
    }

    @Test
    void shouldApplyReplayLimitAfterLastEventId() throws Exception {
        setField(eventStore, "replayLimit", 2);

        eventStore.append(new SseBusinessRiskEvent("e1", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e2", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e3", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e4", "s1", "t1", "task_processing", "{}"));

        List<SseBusinessRiskEvent> replay = eventStore.replayFrom("s1", "e1");

        assertThat(replay).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e3", "e4");
    }

    @Test
    void shouldEnforcePerTaskLimit() throws Exception {
        setField(eventStore, "maxEventsPerTask", 2);

        eventStore.append(new SseBusinessRiskEvent("e1", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e2", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e3", "s1", "t1", "task_processing", "{}"));

        List<SseBusinessRiskEvent> replay = eventStore.replayFrom("s1", null);

        assertThat(replay).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e2", "e3");
    }

    @Test
    void shouldEnforcePerSessionLimit() throws Exception {
        setField(eventStore, "maxEventsPerSession", 3);

        eventStore.append(new SseBusinessRiskEvent("e1", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e2", "s1", "t2", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e3", "s1", "t3", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e4", "s1", "t4", "task_processing", "{}"));

        List<SseBusinessRiskEvent> replay = eventStore.replayFrom("s1", null);

        assertThat(replay).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e2", "e3", "e4");
    }

    @Test
    void shouldEnforceGlobalLimitAcrossSessions() throws Exception {
        setField(eventStore, "maxTotalEvents", 3);

        eventStore.append(new SseBusinessRiskEvent("e1", "s1", "t1", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e2", "s2", "t2", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e3", "s1", "t3", "task_processing", "{}"));
        eventStore.append(new SseBusinessRiskEvent("e4", "s2", "t4", "task_processing", "{}"));

        List<SseBusinessRiskEvent> replayS1 = eventStore.replayFrom("s1", null);
        List<SseBusinessRiskEvent> replayS2 = eventStore.replayFrom("s2", null);

        assertThat(replayS1).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e3");
        assertThat(replayS2).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e2", "e4");
    }

    @Test
    void shouldUseRedisReplayWhenPersistenceBackendIsRedis() throws Exception {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        StreamOperations<String, Object, Object> streamOperations = mock(StreamOperations.class);

        when(redisTemplate.opsForStream()).thenReturn(streamOperations);
        when(streamOperations.range(eq("bizrisk:sse:s1"), any())).thenReturn(List.of(
                StreamRecordFixtures.record("bizrisk:sse:s1", "payload", "{\"eventId\":\"e1\",\"sessionId\":\"s1\",\"taskId\":\"t1\",\"type\":\"task_processing\",\"payload\":\"{}\"}")
        ));
        when(redisTemplate.expire(anyString(), any())).thenReturn(true);

        setField(eventStore, "redisTemplate", redisTemplate);
        setField(eventStore, "persistenceBackend", "redis");

        eventStore.append(new SseBusinessRiskEvent("e1", "s1", "t1", "task_processing", "{}"));

        verify(streamOperations).add(any(org.springframework.data.redis.connection.stream.Record.class));

        List<SseBusinessRiskEvent> replay = eventStore.replayFrom("s1", null);
        assertThat(replay).extracting(SseBusinessRiskEvent::getEventId).containsExactly("e1");
    }

    private void setField(Object target, String fieldName, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(target, value);
    }

    private static final class StreamRecordFixtures {
        @SuppressWarnings("unchecked")
        private static MapRecord<String, Object, Object> record(String stream, String key, String value) {
            return (MapRecord<String, Object, Object>) (MapRecord<?, ?, ?>) StreamRecords
                    .mapBacked(java.util.Map.of(key, value))
                    .withStreamKey(stream);
        }
    }
}
