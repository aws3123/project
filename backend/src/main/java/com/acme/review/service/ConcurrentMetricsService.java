package com.acme.review.service;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.LongAdder;

import io.micrometer.core.instrument.*;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.function.LongUnaryOperator;

/**
 * 基于 Micrometer 的并发与指标监控服务。它主要用于实时统计代码审核系统的吞吐量、延迟、并发连接数以及系统负载情况，
 * 为服务的“智能分发”逻辑（ReviewOrchestratorService 中的 doDispatch）提供数据支撑
 * 并发与指标监控服务 (Concurrent Metrics Service)
 * 
 * <p>该服务是整个审核系统的"仪表盘"，主要职责包括：</p>
 * <ul>
 *   <li><b>计数统计：</b>实时追踪提交、完成、失败的任务数量。</li>
 *   <li><b>延迟监控：</b>记录 Python AI 调用及同步/异步流程的端到端耗时。</li>
 *   <li><b>连接管理：</b>监控活跃的 SSE (Server-Sent Events) 连接数，用于实时推送状态。</li>
 *   <li><b>负载计算：</b>提供活跃任务数、平均延迟等指标，供路由决策器判断系统压力。</li>
 * </ul>
 * 
 * <p><b>线程安全说明：</b>使用了 {@link java.util.concurrent.atomic.LongAdder} 和 Micrometer 的线程安全组件，
 * 以适应高并发的微服务环境，避免原子操作的竞争开销。</p>
 */
@Service
public class ConcurrentMetricsService {

    // ==========================================
    // 核心计数器 (Counters)
    // 使用 LongAdder 替代 AtomicLong，高并发下性能更好
    // ===========================================

    /** 累计提交的任务总数 */
    private final LongAdder tasksSubmitted    = new LongAdder();
    
    /** 累计成功完成的任务总数 */
    private final LongAdder tasksCompleted    = new LongAdder();
    
    /** 累计失败的任务总数 */
    private final LongAdder tasksFailed       = new LongAdder();

    /** 累计通过同步模式分发的任务数 */
    private final LongAdder syncDispatched    = new LongAdder();
    
    /** 累计通过异步模式分发的任务数 */
    private final LongAdder asyncDispatched   = new LongAdder();

    /** 当前活跃的 SSE 连接数 (用于实时推送) */
    private final LongAdder activeSseConnections = new LongAdder();

    // ==========================================
    // 耗时记录器 (Timers)
    // 用于统计延迟分布（P50, P90, P95, P99）
    // ==========================================
    
    private final Timer pythonLatencyTimer;
    private final Timer syncLatencyTimer;
    private final Timer asyncLatencyTimer;

    /**
     * 构造函数，初始化 Micrometer 指标注册表
     * 
     * <p>在这里定义了具体的监控指标名称和描述，这些指标通常会被 Prometheus 抓取，
     * 或在 Spring Boot Admin 中展示。</p>
     *
     * @param meterRegistry Micrometer 的指标注册表
     */
    public ConcurrentMetricsService(MeterRegistry meterRegistry) {
        
        // 1. Python AI 调用延迟
        // 描述：仅统计调用 Python 服务本身的耗时
        this.pythonLatencyTimer = Timer.builder("review.python.latency")
                .description("Python review call latency")
                .publishPercentiles(0.5, 0.9, 0.95, 0.99) // 发布关键百分位数指标
                .register(meterRegistry);

        // 2. 同步审核端到端延迟
        // 描述：从接收请求到返回结果的总耗时
        this.syncLatencyTimer = Timer.builder("review.sync.latency")
                .description("End-to-end sync review latency")
                .publishPercentiles(0.5, 0.9, 0.95, 0.99)
                .register(meterRegistry);

        // 3. 异步审核端到端延迟
        // 描述：从任务入队到结果落库的总耗时
        this.asyncLatencyTimer = Timer.builder("review.async.latency")
                .description("End-to-end async review latency")
                .publishPercentiles(0.5, 0.9, 0.95, 0.99)
                .register(meterRegistry);
    }

    // ==========================================
    // 通用计数方法 (Increment)
    // ===========================================

    /** 记录任务提交 */
    public void recordSubmit()       { tasksSubmitted.increment(); }
    
    /** 记录任务成功完成 */
    public void recordComplete()     { tasksCompleted.increment(); }
    
    /** 记录任务失败 */
    public void recordFailure()      { tasksFailed.increment(); }
    
    /** 记录同步分发 */
    public void recordSync()         { syncDispatched.increment(); }
    
    /** 记录异步分发 */
    public void recordAsync()        { asyncDispatched.increment(); }

    // ==========================================
    // SSE 连接管理
    // ==========================================
    
    /** 记录新的 SSE 连接建立 */
    public void recordSseConnect()   { activeSseConnections.increment(); }
    
    /** 记录 SSE 连接断开 */
    public void recordSseDisconnect(){ activeSseConnections.decrement(); }

    // ==========================================
    // 耗时记录方法 (Latency)
    // ==========================================
    
    /**
     * 记录 Python 调用耗时
     * @param millis 耗时(毫秒)
     */
    public void recordPythonLatency(long millis) {
        pythonLatencyTimer.record(Duration.ofMillis(millis));
    }

    /**
     * 记录同步流程耗时
     * @param millis 耗时(毫秒)
     */
    public void recordSyncLatency(long millis) {
        syncLatencyTimer.record(Duration.ofMillis(millis));
    }

    /**
     * 记录异步流程耗时
     * @param millis 耗时(毫秒)
     */
    public void recordAsyncLatency(long millis) {
        asyncLatencyTimer.record(Duration.ofMillis(millis));
    }

    // ==========================================
    // 计算属性与快照 (Computed Metrics)
    // ==========================================
    
    /**
     * 获取当前活跃的任务数 (正在处理中的任务)
     * 
     * <p>计算逻辑：提交总数 - 完成总数 - 失败总数</p>
     * <p>注意：由于 LongAdder 只能转为 int，这里做了 Math.max 防止负数。</p>
     *
     * @return 活跃任务数量
     */
    public int getActiveCount() {
        return Math.max(0, tasksSubmitted.intValue() - tasksCompleted.intValue() - tasksFailed.intValue());
    }

    /**
     * 获取当前活跃的 SSE 连接数
     * @return 连接数
     */
    public int getActiveSseConnections() {
        return activeSseConnections.intValue();
    }

    /**
     * 计算 Python 调用的平均延迟
     * 
     * <p>注意：这是基于已完成任务的平均值。</p>
     *
     * @return 平均延迟(毫秒)
     */
    public double getAvgPythonLatency() {
        long completed = tasksCompleted.longValue();
        return completed > 0
                ? pythonLatencyTimer.totalTime(TimeUnit.MILLISECONDS) / (double) completed
                : 0;
    }

    /**
     * 获取指标快照
     * 
     * <p>用于将所有监控数据打包，通常用于暴露给监控端点 (Endpoint) 或健康检查。</p>
     *
     * @return 包含所有关键指标的 Map
     */
    public Map<String, Object> snapshot() {
        return Map.of(
            "submitted", tasksSubmitted.longValue(),
            "completed", tasksCompleted.longValue(),
            "failed", tasksFailed.longValue(),
            "active", getActiveCount(), // 当前并发数
            "syncDispatched", syncDispatched.longValue(),
            "asyncDispatched", asyncDispatched.longValue(),
            "activeSseConnections", getActiveSseConnections(),
            "avgPythonLatencyMs", getAvgPythonLatency(), // 计算得出
            "meanPythonLatencyMs", pythonLatencyTimer.mean(TimeUnit.MILLISECONDS) // Micrometer 内置均值
        );
    }
}