package com.acme.review.service;

import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class FeedbackService {

    private static final long MAX_METADATA_BYTES = 65535;

    private final FeedbackMapper feedbackMapper;
    private final ObjectMapper objectMapper;

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
            return feedback;
        }

        if (feedback.getCreatedAt() == null) {
            feedback.setCreatedAt(Instant.now());
        }
        feedbackMapper.insert(feedback);
        log.debug("Created feedback id={} taskId={} type={}", feedback.getId(), feedback.getTaskId(), feedback.getFeedbackType());
        return feedback;
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
}
