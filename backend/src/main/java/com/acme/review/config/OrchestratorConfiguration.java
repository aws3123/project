package com.acme.review.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties({
        OrchestratorProperties.class,
        com.acme.review.service.WebhookDedupProperties.class,
        ReviewStreamEventCacheProperties.class
})
public class OrchestratorConfiguration {
}
