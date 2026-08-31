package com.acme.review.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Redis-backed session memory snapshot service.
 *
 * Persists proposed memory updates from the Python analysis layer into Redis
 * so that stateless Python workers can recover session context after reconnection.
 */
@Service
@Slf4j
public class SessionMemoryService {

    private static final String MEMORY_KEY_PREFIX = "memory:";

    private final ObjectMapper objectMapper;

    @Autowired(required = false)
    private StringRedisTemplate redisTemplate;

    @Value("${business-risk.memory.ttl-seconds:7200}")
    private long ttlSeconds;

    @Value("${business-risk.memory.redis-key-prefix:memory:}")
    private String redisKeyPrefix;

    public SessionMemoryService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * Load the memory context (a dict) for a session from Redis.
     *
     * @return the memory context map, or empty map if none exists or Redis is unavailable.
     */
    public Map<String, Object> loadMemoryContext(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return Map.of();
        }
        if (!useRedis()) {
            return Map.of();
        }

        try {
            String raw = redisTemplate.opsForValue().get(redisKey(sessionId));
            if (raw == null || raw.isBlank()) {
                log.debug("No session memory found for sessionId={}", sessionId);
                return Map.of();
            }

            @SuppressWarnings("unchecked")
            Map<String, Object> snapshot = objectMapper.readValue(raw, HashMap.class);
            Object context = snapshot.get("memory_context");
            if (context instanceof Map<?, ?> memoryContext) {
                log.info("Loaded session memory for sessionId={} version={}",
                        sessionId, snapshot.get("memory_version"));
                return new HashMap<>((Map<String, Object>) memoryContext);
            }
            return Map.of();
        } catch (Exception ex) {
            log.warn("Failed to load session memory for sessionId={}", sessionId, ex);
            return Map.of();
        }
    }

    /**
     * Persist proposed memory updates to Redis.
     */
    public void saveProposedUpdates(String sessionId, Map<String, Object> proposedUpdates) {
        if (sessionId == null || sessionId.isBlank()) {
            return;
        }
        if (proposedUpdates == null || proposedUpdates.isEmpty()) {
            return;
        }
        if (!useRedis()) {
            return;
        }

        try {
            Map<String, Object> snapshot = new HashMap<>();
            snapshot.put("memory_context", proposedUpdates);
            snapshot.put("memory_version", "");
            snapshot.put("updated_at", Instant.now().toString());

            String payload = objectMapper.writeValueAsString(snapshot);
            redisTemplate.opsForValue().set(
                    redisKey(sessionId),
                    payload,
                    Duration.ofSeconds(ttlSeconds)
            );
            log.info("Saved session memory for sessionId={} fields={}",
                    sessionId, proposedUpdates.keySet());
        } catch (JsonProcessingException ex) {
            log.warn("Failed to serialize session memory for sessionId={}", sessionId, ex);
        } catch (Exception ex) {
            log.warn("Failed to save session memory for sessionId={}", sessionId, ex);
        }
    }

    /**
     * Remove a session memory snapshot from Redis.
     */
    public void deleteSessionMemory(String sessionId) {
        if (sessionId == null || sessionId.isBlank() || !useRedis()) {
            return;
        }
        try {
            redisTemplate.delete(redisKey(sessionId));
            log.info("Deleted session memory for sessionId={}", sessionId);
        } catch (Exception ex) {
            log.warn("Failed to delete session memory for sessionId={}", sessionId, ex);
        }
    }

    private String redisKey(String sessionId) {
        return redisKeyPrefix + sessionId;
    }

    private boolean useRedis() {
        return redisTemplate != null;
    }
}
