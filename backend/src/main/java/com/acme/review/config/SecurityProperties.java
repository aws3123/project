package com.acme.review.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "security")
public record SecurityProperties(
        String headerName,
        String apiKey,
        String callbackToken
) {
}
