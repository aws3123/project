package com.acme.review.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "orchestrator")
public record OrchestratorProperties(
    int corePoolSize,
    int maxPoolSize,
    int queueCapacity,
    long keepAliveSeconds,
    int syncTimeoutMs,
    int asyncTimeoutMs
) {
    public OrchestratorProperties {
        if (corePoolSize <= 0) corePoolSize = Runtime.getRuntime().availableProcessors();
        if (maxPoolSize <= 0) maxPoolSize = corePoolSize * 4;
        if (queueCapacity <= 0) queueCapacity = 200;
        if (keepAliveSeconds <= 0) keepAliveSeconds = 60;
        if (syncTimeoutMs <= 0) syncTimeoutMs = 5000;
        if (asyncTimeoutMs <= 0) asyncTimeoutMs = 60000;
    }
}
