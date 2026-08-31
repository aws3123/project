package com.acme.review.service;

import com.acme.review.dto.BusinessRiskWorkerHeartbeatRequest;
import com.acme.review.dto.BusinessRiskWorkerRegistrySnapshot;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Service
@RequiredArgsConstructor
@Slf4j
public class BusinessRiskWorkerRegistryService {

    private final ObjectMapper objectMapper;

    @Autowired(required = false)
    private StringRedisTemplate redisTemplate;

    @Value("${business-risk.worker.redis-key-prefix:bizrisk:worker:}")
    private String redisKeyPrefix;

    @Value("${business-risk.worker.ttl-seconds:45}")
    private long ttlSeconds;

    @Value("${business-risk.worker.fresh-seconds:45}")
    private long freshSeconds;

    private final Map<String, StoredHeartbeat> localHeartbeats = new ConcurrentHashMap<>();

    public void upsert(BusinessRiskWorkerHeartbeatRequest request) {
        validate(request);
        StoredHeartbeat storedHeartbeat = new StoredHeartbeat();
        storedHeartbeat.setInstanceId(request.getInstanceId());
        storedHeartbeat.setHeartbeat(request);
        storedHeartbeat.setLastSeenAt(Instant.now());

        if (useRedis()) {
            try {
                String payload = objectMapper.writeValueAsString(storedHeartbeat);
                redisTemplate.opsForValue().set(redisKey(request.getInstanceId()), payload, Duration.ofSeconds(ttlSeconds));
                return;
            } catch (Exception ex) {
                log.warn("failed to write business risk worker heartbeat to redis instanceId={}", request.getInstanceId(), ex);
            }
        }

        localHeartbeats.put(request.getInstanceId(), storedHeartbeat);
    }

    public BusinessRiskWorkerRegistrySnapshot snapshot(String schemaVersion, String javaPreprocessVersion) {
        List<StoredHeartbeat> heartbeats = listHeartbeats();
        Instant now = Instant.now();
        BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();

        int activeWorkers = 0;
        int readyWorkers = 0;
        int staleWorkers = 0;
        int versionMatchedWorkers = 0;
        int availableSlots = 0;
        int freshReadyWorkers = 0;

        for (StoredHeartbeat storedHeartbeat : heartbeats) {
            if (storedHeartbeat == null || storedHeartbeat.getHeartbeat() == null) {
                continue;
            }
            activeWorkers++;
            boolean fresh = storedHeartbeat.getLastSeenAt() != null
                    && storedHeartbeat.getLastSeenAt().isAfter(now.minusSeconds(freshSeconds));
            if (!fresh) {
                staleWorkers++;
                continue;
            }

            BusinessRiskWorkerHeartbeatRequest heartbeat = storedHeartbeat.getHeartbeat();
            boolean ready = "UP".equalsIgnoreCase(heartbeat.getReadiness());
            boolean versionMatched = supports(heartbeat.getSchemaVersionsSupported(), schemaVersion)
                    && supports(heartbeat.getJavaPreprocessVersionsSupported(), javaPreprocessVersion);

            if (ready) {
                freshReadyWorkers++;
            }
            if (versionMatched) {
                versionMatchedWorkers++;
            }
            if (ready && versionMatched) {
                readyWorkers++;
                availableSlots += Math.max(0, heartbeat.getMaxConcurrency() - heartbeat.getInflightCount());
            }
        }

        snapshot.setActiveWorkers(activeWorkers);
        snapshot.setReadyWorkers(readyWorkers);
        snapshot.setStaleWorkers(staleWorkers);
        snapshot.setVersionMatchedWorkers(versionMatchedWorkers);
        snapshot.setAvailableSlots(Math.max(0, availableSlots));

        if (freshReadyWorkers <= 0) {
            snapshot.setDispatchAllowed(false);
            snapshot.setBlockReason(staleWorkers > 0 ? "PYTHON_HEARTBEAT_STALE" : "PYTHON_WORKER_UNAVAILABLE");
        } else if (versionMatchedWorkers <= 0) {
            snapshot.setDispatchAllowed(false);
            snapshot.setBlockReason("PYTHON_WORKER_VERSION_MISMATCH");
        } else if (readyWorkers <= 0 || availableSlots <= 0) {
            snapshot.setDispatchAllowed(false);
            snapshot.setBlockReason("PYTHON_WORKER_UNAVAILABLE");
        } else {
            snapshot.setDispatchAllowed(true);
        }
        return snapshot;
    }

    public BusinessRiskWorkerRegistrySnapshot snapshot() {
        return snapshot(null, null);
    }

    private List<StoredHeartbeat> listHeartbeats() {
        if (useRedis()) {
            try {
                Set<String> keys = redisTemplate.keys(redisKeyPrefix + "*");
                if (keys != null && !keys.isEmpty()) {
                    List<StoredHeartbeat> heartbeats = new ArrayList<>();
                    for (String key : keys) {
                        String value = redisTemplate.opsForValue().get(key);
                        if (value == null || value.isBlank()) {
                            continue;
                        }
                        heartbeats.add(objectMapper.readValue(value, StoredHeartbeat.class));
                    }
                    return heartbeats;
                }
            } catch (Exception ex) {
                log.warn("failed to read business risk worker heartbeats from redis", ex);
            }
        }

        Instant cutoff = Instant.now().minusSeconds(ttlSeconds);
        localHeartbeats.entrySet().removeIf(entry -> entry.getValue().getLastSeenAt() == null || entry.getValue().getLastSeenAt().isBefore(cutoff));
        return new ArrayList<>(localHeartbeats.values());
    }

    private boolean supports(List<String> supportedVersions, String expectedVersion) {
        if (expectedVersion == null || expectedVersion.isBlank()) {
            return true;
        }
        if (supportedVersions == null || supportedVersions.isEmpty()) {
            return false;
        }
        return supportedVersions.stream().anyMatch(expectedVersion::equalsIgnoreCase);
    }

    private boolean useRedis() {
        return redisTemplate != null;
    }

    private void validate(BusinessRiskWorkerHeartbeatRequest request) {
        if (request == null || request.getInstanceId() == null || request.getInstanceId().isBlank()) {
            throw new IllegalArgumentException("instance_id is required");
        }
        if (request.getWorkerVersion() == null || request.getWorkerVersion().isBlank()) {
            throw new IllegalArgumentException("worker_version is required");
        }
        if (request.getReadiness() == null || request.getReadiness().isBlank()) {
            throw new IllegalArgumentException("readiness is required");
        }
    }

    private String redisKey(String instanceId) {
        return redisKeyPrefix + instanceId;
    }

    @lombok.Getter
    @lombok.Setter
    public static class StoredHeartbeat {
        private String instanceId;
        private Instant lastSeenAt;
        private BusinessRiskWorkerHeartbeatRequest heartbeat;
    }
}
