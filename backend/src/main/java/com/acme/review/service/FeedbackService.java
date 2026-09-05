package com.acme.review.service;

import com.acme.review.dto.FeedbackEventMessage;
import com.acme.review.entity.OutboxEvent;
import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class FeedbackService {

    private static final long MAX_METADATA_BYTES = 65535;
    private static final String THUMBS_DOWN = "thumbs_down";
    private static final String FEEDBACK_NEGATIVE_EVENT = "FEEDBACK_NEGATIVE";

    private final FeedbackMapper feedbackMapper;
    private final OutboxEventMapper outboxMapper;
    private final ObjectMapper objectMapper;

    @Value("${feedback.export-dir:D:/FeedbackExport}")
    private String exportDir;

    @Transactional
    public UserFeedback submit(UserFeedback feedback) {
        if (feedback.getMetadata() != null && feedback.getMetadata().length() > MAX_METADATA_BYTES) {
            feedback.setMetadata(feedback.getMetadata().substring(0, (int) MAX_METADATA_BYTES));
        }

        List<UserFeedback> existing = feedbackMapper.selectList(
                new LambdaQueryWrapper<UserFeedback>()
                        .eq(UserFeedback::getTaskId, feedback.getTaskId())
                        .eq(UserFeedback::getSessionId, feedback.getSessionId())
                        .eq(UserFeedback::getFeedbackType, feedback.getFeedbackType())
                        .orderByDesc(UserFeedback::getId)
                        .last("LIMIT 1")
        );

        if (!existing.isEmpty()) {
            UserFeedback prev = existing.get(0);
            feedback.setId(prev.getId());
            if (feedback.getCreatedAt() == null) {
                feedback.setCreatedAt(Instant.now());
            }
            feedbackMapper.updateById(feedback);
            log.debug("Updated feedback id={} taskId={} type={}", feedback.getId(), feedback.getTaskId(), feedback.getFeedbackType());
            emitNegativeEventIfNeeded(feedback);
            return feedback;
        }

        if (feedback.getCreatedAt() == null) {
            feedback.setCreatedAt(Instant.now());
        }
        feedbackMapper.insert(feedback);
        log.debug("Created feedback id={} taskId={} type={}", feedback.getId(), feedback.getTaskId(), feedback.getFeedbackType());
        emitNegativeEventIfNeeded(feedback);
        return feedback;
    }

    /**
     * 差评（thumbs_down）与反馈落库同事务写 Outbox，保证 DB ↔ MQ 原子性。
     * 由 OutboxPoller 异步投递到 ai.feedback.events，消费侧做负样本标记。
     */
    private void emitNegativeEventIfNeeded(UserFeedback feedback) {
        if (!THUMBS_DOWN.equals(feedback.getFeedbackType())) {
            return;
        }

        try {
            FeedbackEventMessage message = new FeedbackEventMessage();
            message.setFeedbackId(feedback.getId());
            message.setTaskId(feedback.getTaskId());
            message.setSessionId(feedback.getSessionId());
            message.setFeedbackType(feedback.getFeedbackType());
            message.setCategory(feedback.getCategory());
            message.setComment(feedback.getComment());
            message.setSource(feedback.getSource());
            message.setTraceId(feedback.getTraceId());

            String eventId = UUID.randomUUID().toString();
            message.setMessageId(eventId);

            OutboxEvent event = new OutboxEvent();
            event.setEventId(eventId);
            event.setAggregateType("user_feedback");
            event.setAggregateId(feedback.getTaskId());
            event.setEventType(FEEDBACK_NEGATIVE_EVENT);
            event.setPayload(objectMapper.writeValueAsString(message));
            event.setStatus("PENDING");
            event.setRetryCount(0);
            event.setCreatedAt(Instant.now());
            outboxMapper.insert(event);
            log.info("Negative feedback outbox queued eventId={} taskId={} category={}",
                    eventId, feedback.getTaskId(), feedback.getCategory());
        } catch (Exception e) {
            // Outbox 写入失败让整个事务回滚，避免反馈落库但事件丢失
            throw new IllegalStateException("Failed to queue negative feedback outbox event", e);
        }
    }

    public Map<String, Object> getStats(Instant from, Instant to, String source) {
        List<Map<String, Object>> typeCounts = feedbackMapper.countByType(from, to, source);
        long total = 0;
        long thumbsUp = 0;
        long thumbsDown = 0;
        for (Map<String, Object> row : typeCounts) {
            String type = (String) row.get("feedback_type");
            Number cnt = (Number) row.get("cnt");
            long count = cnt != null ? cnt.longValue() : 0;
            total += count;
            if ("thumbs_up".equals(type)) thumbsUp = count;
            else if ("thumbs_down".equals(type)) thumbsDown = count;
        }

        List<Map<String, Object>> dailyRows = feedbackMapper.dailyBreakdown(from, to, source);
        List<Map<String, Object>> dailyBreakdown = dailyRows.stream()
                .collect(Collectors.groupingBy(r -> (String) r.get("day"),
                        LinkedHashMap::new,
                        Collectors.toMap(
                                r -> (String) r.get("feedback_type"),
                                r -> ((Number) r.get("cnt")).longValue(),
                                (a, b) -> a,
                                LinkedHashMap::new
                        )))
                .entrySet().stream()
                .map(entry -> {
                    Map<String, Object> dayMap = new LinkedHashMap<>();
                    dayMap.put("date", entry.getKey());
                    dayMap.put("thumbs_up", entry.getValue().getOrDefault("thumbs_up", 0L));
                    dayMap.put("thumbs_down", entry.getValue().getOrDefault("thumbs_down", 0L));
                    return dayMap;
                })
                .collect(Collectors.toList());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", total);
        result.put("thumbs_up", thumbsUp);
        result.put("thumbs_down", thumbsDown);
        result.put("ratio", total > 0 ? String.format("%.2f", (double) thumbsUp / total) : "0.00");
        result.put("daily_breakdown", dailyBreakdown);
        return result;
    }

    public IPage<UserFeedback> export(Instant from, Instant to, String source, int page, int size) {
        Page<UserFeedback> pageObj = new Page<>(page, size);
        LambdaQueryWrapper<UserFeedback> wrapper = new LambdaQueryWrapper<UserFeedback>()
                .between(UserFeedback::getCreatedAt, from, to)
                .orderByDesc(UserFeedback::getCreatedAt);
        if (source != null && !source.isBlank()) {
            wrapper.eq(UserFeedback::getSource, source);
        }
        return feedbackMapper.selectPage(pageObj, wrapper);
    }

    /**
     * 把全部反馈分页导出为 JSONL 文件（每行一条反馈，作为事故文档入库的输入）。
     *
     * 逐条以 LinkedHashMap 手动映射字段，规避 MyBatis 实体直接序列化时
     * Instant/Jackson JavaTime 模块的差异问题，保证输出字段稳定。
     *
     * @return {path, count} 生成文件绝对路径与导出条数
     */
    public Map<String, Object> exportAllToFile() {
        try {
            Path dir = Paths.get(exportDir);
            Files.createDirectories(dir);
            String fileName = "feedback_export_" + System.currentTimeMillis() + ".jsonl";
            Path file = dir.resolve(fileName);

            LambdaQueryWrapper<UserFeedback> wrapper =
                    new LambdaQueryWrapper<UserFeedback>().orderByAsc(UserFeedback::getCreatedAt);
            long total = 0;
            int page = 1;
            int size = 500;

            try (BufferedWriter writer = Files.newBufferedWriter(file, StandardCharsets.UTF_8)) {
                while (true) {
                    Page<UserFeedback> pageObj = new Page<>(page, size);
                    IPage<UserFeedback> result = feedbackMapper.selectPage(pageObj, wrapper);
                    List<UserFeedback> records = result.getRecords();
                    if (records.isEmpty()) {
                        break;
                    }
                    for (UserFeedback fb : records) {
                        writer.write(toExportRow(fb));
                        writer.newLine();
                        total++;
                    }
                    if (result.getTotal() <= (long) page * size) {
                        break;
                    }
                    page++;
                }
            }

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("path", file.toAbsolutePath().toString());
            result.put("count", total);
            log.info("Exported {} feedback records to {}", total, file.toAbsolutePath());
            return result;
        } catch (Exception e) {
            throw new IllegalStateException("Failed to export feedback to file", e);
        }
    }

    private String toExportRow(UserFeedback fb) throws Exception {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", fb.getId());
        row.put("taskId", fb.getTaskId());
        row.put("sessionId", fb.getSessionId());
        row.put("feedbackType", fb.getFeedbackType());
        row.put("category", fb.getCategory());
        row.put("comment", fb.getComment());
        row.put("metadata", fb.getMetadata());
        row.put("userAgent", fb.getUserAgent());
        row.put("source", fb.getSource());
        row.put("traceId", fb.getTraceId());
        row.put("createdAt", fb.getCreatedAt() != null ? fb.getCreatedAt().toString() : null);
        return objectMapper.writeValueAsString(row);
    }
}
