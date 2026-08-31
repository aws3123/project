package com.acme.review.filter;

import io.github.resilience4j.ratelimiter.RateLimiter;
import io.github.resilience4j.ratelimiter.RateLimiterConfig;
import io.github.resilience4j.ratelimiter.RateLimiterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.web.servlet.filter.OrderedFilter;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;

/**
 * 基于 Resilience4j RateLimiter 的限流过滤器。
 * 对匹配的 API 路径进行请求限流，超出速率时返回 429 Too Many Requests。
 */
@Slf4j
@Component
public class RateLimitingFilter extends OncePerRequestFilter implements OrderedFilter {

    private static final List<String> DEFAULT_INCLUDE_PATHS = List.of("/api/review/");

    private final RateLimiter rateLimiter;
    private final List<String> includePaths;

    public RateLimitingFilter(Environment env) {
        boolean enabled = env.getProperty("rate-limit.enabled", boolean.class, true);
        long capacity = env.getProperty("rate-limit.capacity", long.class, 100L);
        String[] paths = env.getProperty("rate-limit.include-paths", String[].class);

        this.includePaths = paths != null && paths.length > 0
                ? Arrays.asList(paths) : DEFAULT_INCLUDE_PATHS;

        if (enabled) {
            RateLimiterConfig config = RateLimiterConfig.custom()
                    .limitForPeriod((int) capacity)
                    .limitRefreshPeriod(Duration.ofSeconds(1))
                    .timeoutDuration(Duration.ZERO)
                    .build();
            this.rateLimiter = RateLimiterRegistry.of(config)
                    .rateLimiter("api-rate-limiter", config);
        } else {
            this.rateLimiter = null;
        }

        log.info("Rate limiter initialized: enabled={} capacity={}/s paths={}",
                enabled, capacity, includePaths);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (rateLimiter == null) {
            return true;
        }
        String path = request.getRequestURI();
        if (path == null) {
            return true;
        }
        return includePaths.stream().noneMatch(path::startsWith);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        boolean acquired = rateLimiter.acquirePermission();
        if (acquired) {
            long available = rateLimiter.getMetrics().getAvailablePermissions();
            response.setHeader("X-RateLimit-Remaining", String.valueOf(Math.max(0, available)));
            filterChain.doFilter(request, response);
            return;
        }

        log.warn("Rate limit exceeded path={} method={}",
                request.getRequestURI(), request.getMethod());

        response.setStatus(429);
        response.setHeader("Retry-After", "1");
        response.setContentType("application/json;charset=UTF-8");
        String json = String.format(
                "{\"timestamp\":\"%s\",\"status\":429,\"error\":\"Too Many Requests\",\"message\":\"Rate limit exceeded. Try again later.\",\"path\":\"%s\"}",
                Instant.now().toString(), request.getRequestURI());
        response.getWriter().write(json);
    }

    @Override
    public int getOrder() {
        return OrderedFilter.HIGHEST_PRECEDENCE + 10;
    }
}
