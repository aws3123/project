package com.acme.review.service.strategy;

/**
 * 审核执行策略统一标记接口。
 * 所有策略实现类通过 Spring Map&lt;String, ReviewExecutionStrategy&gt; 自动发现和注入。
 */
public interface ReviewExecutionStrategy {
}
