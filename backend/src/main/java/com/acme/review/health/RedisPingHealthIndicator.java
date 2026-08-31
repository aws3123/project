package com.acme.review.health;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.stereotype.Component;

@Component("redisPing")
@RequiredArgsConstructor
public class RedisPingHealthIndicator implements HealthIndicator {

    private final RedisConnectionFactory redisConnectionFactory;

    @Override
    public Health health() {
        try (RedisConnection connection = redisConnectionFactory.getConnection()) {
            String pong = connection.ping();
            return Health.up().withDetail("ping", pong).build();
        } catch (Exception ex) {
            return Health.down(ex).build();
        }
    }
}
