package com.acme.review.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SessionMemoryServiceTest {

    private StringRedisTemplate redisTemplate;
    private ValueOperations<String, String> valueOps;
    private SessionMemoryService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redisTemplate = mock(StringRedisTemplate.class);
        valueOps = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        service = new SessionMemoryService(new ObjectMapper());
        setField(service, "redisTemplate", redisTemplate);
        setField(service, "redisKeyPrefix", "memory:");
    }

    private void setField(Object target, String fieldName, Object value) {
        try {
            var field = target.getClass().getDeclaredField(fieldName);
            field.setAccessible(true);
            field.set(target, value);
        } catch (Exception ex) {
            throw new RuntimeException(ex);
        }
    }

    @Test
    void shouldLoadMemoryContextFromRedis() throws Exception {
        String snapshot = """
                {"memory_context":{"business_risk_level":"high","violation_count":3},"memory_version":"v2","updated_at":"2026-06-27T10:00:00"}
                """;
        when(valueOps.get("memory:session-1")).thenReturn(snapshot);

        Map<String, Object> result = service.loadMemoryContext("session-1");

        assertThat(result)
                .containsEntry("business_risk_level", "high")
                .containsEntry("violation_count", 3);
    }

    @Test
    void shouldReturnEmptyMapWhenNoRedisEntry() {
        when(valueOps.get("memory:session-1")).thenReturn(null);

        Map<String, Object> result = service.loadMemoryContext("session-1");

        assertThat(result).isEmpty();
    }

    @Test
    void shouldReturnEmptyMapForBlankSession() {
        Map<String, Object> result = service.loadMemoryContext(null);
        assertThat(result).isEmpty();

        result = service.loadMemoryContext("");
        assertThat(result).isEmpty();
    }

    @Test
    void shouldSaveProposedUpdatesToRedis() {
        Map<String, Object> updates = Map.of("business_risk_level", "high", "violation_count", 3);

        service.saveProposedUpdates("session-1", updates);

        verify(valueOps).set(eq("memory:session-1"), anyString(), any(Duration.class));
    }

    @Test
    void shouldSkipSaveForEmptyUpdates() {
        service.saveProposedUpdates("session-1", Map.of());
        verify(valueOps, never()).set(anyString(), anyString(), any(Duration.class));

        service.saveProposedUpdates("session-1", null);
        verify(valueOps, never()).set(anyString(), anyString(), any(Duration.class));
    }

    @Test
    void shouldSkipSaveForBlankSession() {
        service.saveProposedUpdates(null, Map.of("key", "val"));
        verify(valueOps, never()).set(anyString(), anyString(), any(Duration.class));

        service.saveProposedUpdates("", Map.of("key", "val"));
        verify(valueOps, never()).set(anyString(), anyString(), any(Duration.class));
    }

    @Test
    void shouldDeleteSessionMemory() {
        service.deleteSessionMemory("session-1");
        verify(redisTemplate).delete("memory:session-1");
    }
}
