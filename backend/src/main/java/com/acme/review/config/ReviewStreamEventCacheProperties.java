package com.acme.review.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 代码评审同步流式链路的事件缓存配置（Redis Stream）。
 *
 * 用途：同步流式任务前端断开重连时，从 Redis 重放错过的事件并实时尾随，
 * 配合 SyncStrategy 的"断线不取消 Python 订阅"实现快照 + 增量补偿。
 */
@ConfigurationProperties(prefix = "review.sync.event-cache")
public record ReviewStreamEventCacheProperties(
    /** 是否启用事件缓存。关闭时同步链路退化为纯实时转发（旧行为）。 */
    boolean enabled,
    /** Redis Stream key 前缀，key = prefix + taskId。 */
    String redisKeyPrefix,
    /** 每个任务 Stream 的最大事件数，超出按 MAXLEN 截断（只缓存粗粒度进度事件，非 token 级）。 */
    long maxEventsPerTask,
    /** 任务执行期的活跃 TTL（秒），每次写入刷新。 */
    long activeTtlSeconds,
    /** 任务终态后的保留 TTL（秒），用于支持过期后的断线重连窗口。 */
    long terminalTtlSeconds,
    /** 尾随 XREAD BLOCK 阻塞时长（毫秒）。 */
    long tailBlockMs,
    /** 尾随线程池大小。 */
    int tailThreads
) {
    public ReviewStreamEventCacheProperties {
        if (redisKeyPrefix == null || redisKeyPrefix.isBlank()) {
            redisKeyPrefix = "review:sse:";
        }
        if (maxEventsPerTask <= 0) {
            maxEventsPerTask = 500;
        }
        if (activeTtlSeconds <= 0) {
            activeTtlSeconds = 240;
        }
        if (terminalTtlSeconds <= 0) {
            terminalTtlSeconds = 900;
        }
        if (tailBlockMs <= 0) {
            tailBlockMs = 15_000L;
        }
        if (tailThreads <= 0) {
            tailThreads = 64;
        }
    }
}