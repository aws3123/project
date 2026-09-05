package com.acme.review.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.math.BigDecimal;

/**
 * 计费相关配置。
 *
 * <p>{@code unitPricePerK} 是"元/千 token"的单价快照：记账时直接复制到
 * {@code token_usage_record.unit_price_snapshot}，后续调价只影响新记录。</p>
 */
@ConfigurationProperties(prefix = "billing")
public record BillingProperties(
    boolean enabled,
    BigDecimal unitPricePerK,
    long maxTokensPerSubmitter
) {
    public BillingProperties {
        if (unitPricePerK == null) {
            unitPricePerK = new BigDecimal("0.0010");
        }
        if (maxTokensPerSubmitter <= 0) {
            maxTokensPerSubmitter = 1_000_000L;
        }
    }
}
