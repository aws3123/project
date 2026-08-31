package com.acme.review.health;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

@Component("mq")
public class MqHealthIndicator implements HealthIndicator {

    @Value("${spring.cloud.stream.defaultBinder:kafka}")
    private String binder;

    @Override
    public Health health() {
        if (binder == null || binder.isBlank()) {
            return Health.down().withDetail("reason", "default binder is blank").build();
        }
        return Health.up().withDetail("binder", binder).build();
    }
}
