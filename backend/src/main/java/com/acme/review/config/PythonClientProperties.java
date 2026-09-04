package com.acme.review.config;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter
@Setter
@NoArgsConstructor
@ConfigurationProperties(prefix = "python")
public class PythonClientProperties {

    private String baseUrl;
    private String syncPath;
    private String logsPath;
    private long timeoutMs;
    private int connectTimeoutMs = 3000;
    private boolean discoveryEnabled = false;
    private String businessRiskHealthPath = "/ai/health/business-risk-source";
}
