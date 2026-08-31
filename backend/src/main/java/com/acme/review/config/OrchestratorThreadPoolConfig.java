package com.acme.review.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

@Configuration
public class OrchestratorThreadPoolConfig {

    @Bean("reviewExecutor")
    public ThreadPoolExecutor reviewExecutor(OrchestratorProperties props) {
        return new ThreadPoolExecutor(
            props.corePoolSize(),
            props.maxPoolSize(),
            props.keepAliveSeconds(),
            TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(props.queueCapacity()),
            new ThreadPoolExecutor.CallerRunsPolicy()
        );
    }
}
