package com.acme.review.controller;

import com.acme.review.config.SecurityProperties;
import com.acme.review.entity.ReviewTaskPayload;
import com.acme.review.repository.mapper.ReviewTaskPayloadMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

/**
 * 内部载荷拉取端点 —— 供 Python 消费 Kafka 任务消息后回源拉取大 payload。
 * 消息只带 taskId + 小字段，diffContent / entities / relations 统一走本端点，
 * 避免 Kafka 大消息（1MB 上限）问题，且同一 taskId 重复拉取无副作用（幂等读）。
 */
@RestController
@RequestMapping("/api/internal/review")
@RequiredArgsConstructor
public class InternalReviewPayloadController {

    private final ReviewTaskPayloadMapper payloadMapper;
    private final SecurityProperties securityProperties;
    private final ObjectMapper objectMapper;

    private static final TypeReference<List<Map<String, Object>>> JSON_LIST_TYPE =
            new TypeReference<>() {};

    @GetMapping("/payload/{taskId}")
    public ResponseEntity<Map<String, Object>> getPayload(
            @PathVariable String taskId,
            HttpServletRequest servletRequest
    ) {
        String providedKey = servletRequest.getHeader(securityProperties.headerName());
        if (providedKey == null || providedKey.isBlank()
                || !securityProperties.apiKey().equals(providedKey)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid API key");
        }

        ReviewTaskPayload payload = payloadMapper.findByTaskId(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Payload not found: " + taskId));

        Map<String, Object> body = new java.util.LinkedHashMap<>();
        body.put("taskId", taskId);
        body.put("diffContent", payload.getDiffContent());
        body.put("entities", parseJsonList(payload.getEntitiesJson()));
        body.put("relations", parseJsonList(payload.getRelationsJson()));
        return ResponseEntity.ok(body);
    }

    private List<Map<String, Object>> parseJsonList(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, JSON_LIST_TYPE);
        } catch (Exception e) {
            return List.of();
        }
    }
}
