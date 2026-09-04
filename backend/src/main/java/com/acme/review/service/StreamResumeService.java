package com.acme.review.service;

import com.acme.review.config.ReviewStreamEventCacheProperties;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.acme.review.service.ReviewStreamEventStore.StoredEvent;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 同步流式任务断线重连服务。
 *
 * 调用方（NotificationController）在收到 Last-Event-ID 或确认任务存在缓存后，
 * 先尝试本服务的 resume：从 Redis 重放缺失事件，再阻塞尾随实时续流；终态事件
 * 则 complete。若判断为非同步流式任务（如异步链路），返回 false，由调用方退回
 * 原有 sseRegistry 注册逻辑，保证异步链路行为零改动。
 *
 * DB 兜底：缓存不存在但任务已终态时（缓存过期），从数据库合成一条终态事件，
 * 客户端据此停止重连，完整内容仍可通过任务查询接口获取。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StreamResumeService {

    /** 与同步流式 emitter 兜底超时一致，需大于活跃 TTL，保证尾部补看窗口。 */
    private static final long EMITTER_TIMEOUT_MS = 180_000L;
    private static final int READ_BATCH = 32;
    private static final long IDLE_TIMEOUT_MS = 200_000L;

    private static final String EVENT_RUN_FINISHED = "run_finished";
    private static final String EVENT_RUN_ERROR = "run_error";

    private final ReviewStreamEventStore eventStore;
    private final ReviewStreamEventCacheProperties props;
    private final ReviewTaskMapper taskRepo;
    private final ReviewResultMapper resultRepo;
    private final ObjectMapper objectMapper;

    private ExecutorService tailExecutor;

    // 由 @RequiredArgsConstructor 生成构造函数，此处通过 init() 用 props 初始化线程池
    /** 该任务是否已有同步流式事件缓存（用于 controller 分流判定）。 */
    public boolean hasCachedStream(String taskId) {
        return eventStore.enabled() && eventStore.hasEvents(taskId);
    }

    private void ensureExecutor() {
        if (tailExecutor == null) {
            synchronized (this) {
                if (tailExecutor == null) {
                    tailExecutor = Executors.newFixedThreadPool(Math.max(1, props.tailThreads()));
                }
            }
        }
    }

    /**
     * 尝试对任务建立断线补偿连接。
     * @return true 表示已接管并写入了发射器（调用方应返回该 emitter）；false 表示非本服务场景。
     */
    public boolean tryResume(String taskId, String lastEventId, SseEmitter emitter) {
        if (!eventStore.enabled()) {
            return false;
        }
        ensureExecutor();

        List<StoredEvent> replay = eventStore.replayAfter(taskId, lastEventId);
        // 无缓存：缓存存在与否是判断"是否是同步流式任务"的关键依据
        if (!eventStore.hasEvents(taskId)) {
            return handleNoCache(taskId, emitter);
        }

        String cursor = lastEventId;
        boolean terminal = false;
        for (StoredEvent event : replay) {
            send(emitter, event);
            cursor = event.eventId();
            if (isTerminal(event.eventName())) {
                terminal = true;
            }
        }
        if (terminal) {
            safeComplete(emitter);
            return true;
        }

        AtomicBoolean running = new AtomicBoolean(true);
        armEmitter(emitter, running);
        final String tailFrom = cursor;
        tailExecutor.execute(() -> tail(taskId, tailFrom, emitter, running));
        return true;
    }

    /** 缓存为空：仅当任务已终态时从 DB 合成一条终态事件；否则退回原逻辑。 */
    private boolean handleNoCache(String taskId, SseEmitter emitter) {
        ReviewTask task = taskRepo.findByTaskId(taskId).orElse(null);
        if (task == null || task.getStatus() == null || !task.getStatus().isTerminal()) {
            return false;
        }
        try {
            String terminalName;
            String data;
            ReviewResult result = resultRepo.findByTaskId(taskId).orElse(null);
            if (task.getStatus() == ReviewTaskStatus.FAILED) {
                terminalName = EVENT_RUN_ERROR;
                String errorMessage = result != null && result.getErrorMessage() != null
                        ? result.getErrorMessage() : "Task failed";
                data = writeJson(Map.of(
                        "taskId", taskId,
                        "errorCode", "TASK_FAILED",
                        "errorMessage", errorMessage));
            } else {
                terminalName = EVENT_RUN_FINISHED;
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("taskId", taskId);
                payload.put("result", toSyncResponse(taskId, result));
                data = writeJson(payload);
            }
            send(emitter, new StoredEvent(taskId + "-terminal-" + System.currentTimeMillis(), terminalName, data));
            safeComplete(emitter);
            return true;
        } catch (Exception ex) {
            log.warn("review stream resume DB synthesis failed taskId={}: {}", taskId, ex.getMessage());
            return false;
        }
    }

    private ReviewSyncResponse toSyncResponse(String taskId, ReviewResult result) {
        ReviewSyncResponse response = new ReviewSyncResponse();
        response.setTaskId(taskId);
        if (result != null) {
            BigDecimal score = result.getRiskScore();
            response.setRiskScore(score != null ? score.doubleValue() : 0d);
            response.setRiskSummary(result.getRiskSummary());
            response.setNeedHumanReview(result.isNeedHumanReview());
            if (result.getDetails() != null) {
                List<String> details = new ArrayList<>();
                for (String line : result.getDetails().split("\n")) {
                    details.add(line);
                }
                response.setDetails(details);
            }
        }
        return response;
    }

    /** 尾随循环：XREAD BLOCK 读新事件，遇到终态 complete；客户端断开/超时则退出。 */
    private void tail(String taskId, String cursor, SseEmitter emitter, AtomicBoolean running) {
        String current = cursor;
        long lastEventAt = System.currentTimeMillis();
        Duration block = Duration.ofMillis(props.tailBlockMs());
        while (running.get()) {
            List<StoredEvent> events = eventStore.readNew(taskId, current, block, READ_BATCH);
            for (StoredEvent event : events) {
                current = event.eventId();
                lastEventAt = System.currentTimeMillis();
                if (isTerminal(event.eventName())) {
                    send(emitter, event);
                    running.set(false);
                    safeComplete(emitter);
                    return;
                }
                send(emitter, event);
            }
            // 空闲兜底：超过发射器超时则停止，依赖 emitter 自身的 onTimeout 收尾
            if (System.currentTimeMillis() - lastEventAt > IDLE_TIMEOUT_MS) {
                running.set(false);
                safeComplete(emitter);
                return;
            }
            if (events.isEmpty()) {
                Thread.yield();
            }
        }
    }

    private boolean isTerminal(String eventName) {
        return EVENT_RUN_FINISHED.equals(eventName) || EVENT_RUN_ERROR.equals(eventName);
    }

    private void armEmitter(SseEmitter emitter, AtomicBoolean running) {
        emitter.onCompletion(() -> running.set(false));
        emitter.onError(e -> {
            running.set(false);
            safeComplete(emitter);
        });
        emitter.onTimeout(() -> {
            running.set(false);
            safeComplete(emitter);
        });
    }

    private void send(SseEmitter emitter, StoredEvent event) {
        try {
            emitter.send(SseEmitter.event()
                    .id(event.eventId())
                    .name(event.eventName())
                    .data(event.data()));
        } catch (Exception ex) {
            log.debug("resume SSE forward failed eventId={}: {}", event.eventId(), ex.getMessage());
        }
    }

    private void safeComplete(SseEmitter emitter) {
        try {
            emitter.complete();
        } catch (Exception ignored) {
            // 已 complete 或已超时，忽略
        }
    }

    private String writeJson(Map<String, ?> payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception ex) {
            throw new RuntimeException(ex);
        }
    }

    @PreDestroy
    void destroy() {
        if (tailExecutor != null) {
            tailExecutor.shutdownNow();
        }
    }
}