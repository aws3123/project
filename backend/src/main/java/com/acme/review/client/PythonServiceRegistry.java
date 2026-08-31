package com.acme.review.client;

import com.acme.review.config.PythonClientProperties;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RList;
import org.redisson.api.RScoredSortedSet;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 基于 Redis 的 Python 服务注册发现。
 * Python 实例通过心跳维持注册，Java 侧随机负载均衡 + 健康检查自动踢出。
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "python", name = "discovery-enabled", havingValue = "true")
public class PythonServiceRegistry {

    private static final String INSTANCES_KEY = "python:instances";
    private static final String HEARTBEATS_KEY = "python:heartbeats";
    private static final int HEALTH_CHECK_INTERVAL_MS = 15_000;
    private static final int HEARTBEAT_TIMEOUT_SEC = 60;

    @Autowired(required = false)
    private RedissonClient redisson;

    private final PythonClientProperties pyProps;

    public PythonServiceRegistry(PythonClientProperties pyProps) {
        this.pyProps = pyProps;
    }

    public List<String> getAvailableInstances() {
        if (redisson == null) {
            return List.of();
        }
        RScoredSortedSet<String> heartbeats = redisson.getScoredSortedSet(HEARTBEATS_KEY);
        long cutoff = System.currentTimeMillis() / 1000 - HEARTBEAT_TIMEOUT_SEC;
        heartbeats.removeRangeByScore(0, false, cutoff, false);

        RList<String> instances = redisson.getList(INSTANCES_KEY);
        return instances.readAll();
    }

    public String getNextInstance() {
        List<String> instances = getAvailableInstances();
        if (instances.isEmpty()) {
            log.debug("No Python instances registered, falling back to baseUrl");
            return pyProps.getBaseUrl();
        }
        int index = ThreadLocalRandom.current().nextInt(instances.size());
        return instances.get(index);
    }

    /**
     * 定期健康检查，踢出不可达实例。
     */
    @Scheduled(fixedDelay = HEALTH_CHECK_INTERVAL_MS)
    public void healthCheck() {
        List<String> instances = getAvailableInstances();
        for (String instance : instances) {
            if (!isHealthy(instance)) {
                log.warn("Python instance {} is unhealthy, removing from registry", instance);
                remove(instance);
            }
        }
    }

    public void remove(String instanceUrl) {
        if (redisson == null) {
            return;
        }
        redisson.getList(INSTANCES_KEY).remove(instanceUrl);
        redisson.getScoredSortedSet(HEARTBEATS_KEY).remove(instanceUrl);
    }

    private boolean isHealthy(String baseUrl) {
        try {
            java.net.http.HttpClient client = java.net.http.HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(3))
                    .build();
            java.net.http.HttpRequest req = java.net.http.HttpRequest.newBuilder(
                            java.net.URI.create(baseUrl + "/ai/health"))
                    .timeout(Duration.ofSeconds(3))
                    .GET()
                    .build();
            java.net.http.HttpResponse<String> resp = client.send(req,
                    java.net.http.HttpResponse.BodyHandlers.ofString());
            return resp.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }
}
