package com.acme.review.controller;

import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.dto.TaskListResponse;
import com.acme.review.service.ReviewService;
import com.acme.review.service.strategy.AsyncStrategy;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/review/tasks")
@Validated
@RequiredArgsConstructor
public class TaskController {

    private final ReviewService reviewService;
    private final AsyncStrategy asyncStrategy;

    @GetMapping("/{taskId}")
    public ResponseEntity<TaskDetailResponse> getTask(@PathVariable String taskId) {
        return reviewService.getTaskDetail(taskId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping
    public ResponseEntity<TaskListResponse> listTasks(
            @RequestParam(defaultValue = "1") @Min(1) int page,
            @RequestParam(defaultValue = "5") @Min(1) @Max(100) int size,
            @RequestParam(required = false) String projectId,
            @RequestParam(required = false) String status
    ) {
        return ResponseEntity.ok(reviewService.listTasks(page, size, projectId, status));
    }

    @PostMapping("/{taskId}/retry")
    public ResponseEntity<Map<String, String>> retryTask(@PathVariable String taskId) {
        try {
            asyncStrategy.retryStuckTask(taskId);
            return ResponseEntity.ok(Map.of("taskId", taskId, "status", "RETRYING"));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.notFound().build();
        }
    }
}
