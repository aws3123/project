package com.acme.review.config;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

@Getter
@Setter
@NoArgsConstructor
@ConfigurationProperties(prefix = "rate-limit")
public class RateLimitProperties {

    /** 是否启用限流 */
    private boolean enabled = true;

    /** 令牌桶容量（允许的突发最大请求数） */
    private long capacity = 100;

    /** 每秒令牌补充速率 */
    private long refillRate = 50;

    /** 限流生效的路径模式 */
    private List<String> includePaths = List.of("/api/review/**");
}
