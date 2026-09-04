package com.acme.review.service;

import com.acme.review.config.ReviewStreamEventCacheProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 代码评审同步流式任务的事件缓存存储（Redis Stream）。
 *
 * 写入侧：append 将事件按 [taskId] 追加到 Stream，写入即实时的唯一权威（事件 ID =
 * Redis RecordId，任务维度严格单调递增）。失败返回 null，由调用方降级为本地 seq。
 * 读取侧重连：replayAfter 排他重放历史，readNew 以 $(latest) 或排他 offset 阻塞尾随。
 *
 * 该存储为多实例安全设计，不依赖任何进程内状态；Redis 故障时写入静默降级，
 * 不影响实时转发主链路（业务结果的真相源始终是数据库）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ReviewStreamEventStore {

    private final StringRedisTemplate redisTemplate;
    private final ReviewStreamEventCacheProperties props;

    private static final String FIELD_NAME = "name";
    private static final String FIELD_DATA = "data";

    /** Redis 中的一条缓存事件。 */
    public record StoredEvent(String eventId, String eventName, String data) {
    }

    public boolean enabled() {
        return props.enabled();
    }

    /** 当前任务缓存是否已有事件（用于区分同步任务与异步任务）。 */
    public boolean hasEvents(String taskId) {
        return size(taskId) > 0;
    }

    public long size(String taskId) {
        try {
            Long len = redisTemplate.opsForStream().size(key(taskId));
            return len == null ? 0 : len;
        } catch (Exception ex) {
            log.debug("review stream size failed taskId={}: {}", taskId, ex.getMessage());
            return 0;
        }
    }

    /**
     * 追加一条事件。成功返回 RecordId 字符串（作为 SSE 事件 id），失败返回 null。
     * 追加后刷新活跃 TTL。
     */
    public String append(String taskId, String eventName, String data) {
        try {
            Map<String, Object> fields = new LinkedHashMap<>();
            fields.put(FIELD_NAME, eventName);
            fields.put(FIELD_DATA, data);
            RecordId recordId = redisTemplate.opsForStream().add(key(taskId), fields);
            if (recordId == null) {
                return null;
            }
            if (props.maxEventsPerTask() > 0) {
                redisTemplate.opsForStream().trim(key(taskId), props.maxEventsPerTask());
            }
            if (props.activeTtlSeconds() > 0) {
                redisTemplate.expire(key(taskId), Duration.ofSeconds(props.activeTtlSeconds()));
            }
            return recordId.toString();
        } catch (Exception ex) {
            log.warn("review stream append failed taskId={} event={}: {}", taskId, eventName, ex.getMessage());
            return null;
        }
    }

    /** 终态事件写入后调用：切到更长的保留 TTL，支持断线重连窗口。 */
    public void markTerminal(String taskId) {
        try {
            if (props.terminalTtlSeconds() > 0) {
                redisTemplate.expire(key(taskId), Duration.ofSeconds(props.terminalTtlSeconds()));
            }
        } catch (Exception ex) {
            log.debug("review stream markTerminal failed taskId={}: {}", taskId, ex.getMessage());
        }
    }

    /** 重放 lastEventId（不含）之后的全部历史。lastEventId 为空则全量。 */
    public List<StoredEvent> replayAfter(String taskId, String lastEventId) {
        try {
            Range<String> range;
            if (lastEventId == null || lastEventId.isBlank()) {
                range = Range.unbounded();
            } else {
                range = Range.of(Range.Bound.exclusive(lastEventId), Range.Bound.unbounded());
            }
            List<MapRecord<String, Object, Object>> records =
                    redisTemplate.opsForStream().range(key(taskId), range);
            return toEvents(records, props.maxEventsPerTask());
        } catch (Exception ex) {
            log.warn("review stream replay failed taskId={}: {}", taskId, ex.getMessage());
            return List.of();
        }
    }

    /**
     * 阻塞读取新事件，用于实时尾随。
     * lastEventId 为空表示只读这一刻之后的新事件（$）；否则读取严格大于 lastEventId 的记录。
     * 阻塞超时返回空列表，由调用方循环。
     */
    public List<StoredEvent> readNew(String taskId, String lastEventId, Duration block, int count) {
        try {
            StreamReadOptions options = StreamReadOptions.empty().block(block).count(count);
            ReadOffset offset = (lastEventId == null || lastEventId.isBlank())
                    ? ReadOffset.latest()
                    : ReadOffset.from(lastEventId);
            List<MapRecord<String, Object, Object>> records = redisTemplate.opsForStream()
                    .read(options, StreamOffset.create(key(taskId), offset));
            return toEvents(records, count);
        } catch (Exception ex) {
            log.debug("review stream readNew returned taskId={}: {}", taskId, ex.getMessage());
            return List.of();
        }
    }

    private List<StoredEvent> toEvents(List<MapRecord<String, Object, Object>> records, long cap) {
        if (records == null || records.isEmpty()) {
            return List.of();
        }
        List<StoredEvent> events = new ArrayList<>(records.size());
        for (MapRecord<String, Object, Object> record : records) {
            Object name = record.getValue().get(FIELD_NAME);
            Object data = record.getValue().get(FIELD_DATA);
            events.add(new StoredEvent(
                    record.getId().toString(),
                    name instanceof String s ? s : "message",
                    data instanceof String d ? d : "{}"));
        }
        if (cap > 0 && events.size() > cap) {
            int from = (int) (events.size() - cap);
            return events.subList(Math.max(0, from), events.size());
        }
        return events;
    }

    private String key(String taskId) {
        return props.redisKeyPrefix() + taskId;
    }
}