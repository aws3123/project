package com.acme.review.service;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "webhook")
public record WebhookDedupProperties(
    long dedupLockTtlSeconds
) {
    public WebhookDedupProperties {
        if (dedupLockTtlSeconds <= 0) dedupLockTtlSeconds = 120;
    }
}
