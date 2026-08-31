package com.acme.review.service.strategy;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 审核策略简单工厂。
 * Spring 自动注入 {@code Map<String, ReviewExecutionStrategy>}，Bean 名称为 key。
 */
@Component
@RequiredArgsConstructor
public class ReviewStrategyFactory {

    private final Map<String, ReviewExecutionStrategy> strategyMap;

    public SyncStrategy getSyncStrategy() {
        return getStrategy("syncReviewStrategy", SyncStrategy.class);
    }

    public AsyncStrategy getAsyncStrategy() {
        return getStrategy("asyncReviewStrategy", AsyncStrategy.class);
    }

    public DispatchStrategy getDispatchStrategy() {
        return getStrategy("dispatchReviewStrategy", DispatchStrategy.class);
    }

    private <T extends ReviewExecutionStrategy> T getStrategy(String beanName, Class<T> type) {
        ReviewExecutionStrategy strategy = strategyMap.get(beanName);
        if (strategy == null) {
            throw new IllegalStateException(
                    "No ReviewExecutionStrategy bean found with name: " + beanName);
        }
        return type.cast(strategy);
    }
}
