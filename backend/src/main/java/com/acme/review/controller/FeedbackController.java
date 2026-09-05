package com.acme.review.controller;

import com.acme.review.entity.UserFeedback;
import com.acme.review.service.FeedbackService;
import com.baomidou.mybatisplus.core.metadata.IPage;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/feedback")
@Validated
@RequiredArgsConstructor
public class FeedbackController {

    private final FeedbackService feedbackService;

    @Data
    public static class SubmitRequest {
        @NotBlank(message = "taskId is required")
        private String taskId;

        @NotBlank(message = "sessionId is required")
        private String sessionId;

        @NotBlank(message = "feedbackType is required")
        @Pattern(regexp = "thumbs_up|thumbs_down", message = "feedbackType must be thumbs_up or thumbs_down")
        private String feedbackType;

        private String category;
        private String comment;
        private String metadata;
        private String source;
    }

    @PostMapping("/submit")
    public ResponseEntity<Map<String, Object>> submitFeedback(
            @Valid @RequestBody SubmitRequest request,
            @RequestHeader(value = HttpHeaders.USER_AGENT, required = false) String userAgent,
            @RequestHeader(value = "X-Trace-Id", required = false) String traceId) {

        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId(request.getTaskId());
        feedback.setSessionId(request.getSessionId());
        feedback.setFeedbackType(request.getFeedbackType());
        feedback.setCategory(request.getCategory());
        feedback.setComment(request.getComment());
        feedback.setMetadata(request.getMetadata());
        feedback.setUserAgent(userAgent);
        feedback.setSource(request.getSource() != null ? request.getSource() : "review");
        feedback.setTraceId(traceId);

        UserFeedback saved = feedbackService.submit(feedback);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", saved.getId());
        body.put("status", "accepted");
        return ResponseEntity.status(HttpStatus.CREATED).body(body);
    }

    @GetMapping("/stats")
    public ResponseEntity<Map<String, Object>> getStats(
            @RequestParam Instant from,
            @RequestParam Instant to,
            @RequestParam(required = false) String source) {
        return ResponseEntity.ok(feedbackService.getStats(from, to, source));
    }

    @GetMapping("/export")
    public ResponseEntity<IPage<UserFeedback>> export(
            @RequestParam Instant from,
            @RequestParam Instant to,
            @RequestParam(required = false) String source,
            @RequestParam(defaultValue = "1") @Min(1) int page,
            @RequestParam(defaultValue = "50") @Min(1) @Max(1000) int size) {
        return ResponseEntity.ok(feedbackService.export(from, to, source, page, size));
    }

    @GetMapping("/export-file")
    public ResponseEntity<Map<String, Object>> exportFile() {
        return ResponseEntity.ok(feedbackService.exportAllToFile());
    }
}
