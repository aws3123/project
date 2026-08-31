package com.acme.review.service;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class WebhookDedupServiceTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(WebhookDedupService.class);

    @Test
    void shouldFallbackToLocalLockWhenRedissonMissing() {
        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();

            WebhookDedupService service = context.getBean(WebhookDedupService.class);
            assertThat(service.tryAcquire("lock-key", 120)).isTrue();
            assertThat(service.tryAcquire("lock-key", 120)).isFalse();

            service.release("lock-key");

            assertThat(service.tryAcquire("lock-key", 120)).isTrue();
        });
    }
}
