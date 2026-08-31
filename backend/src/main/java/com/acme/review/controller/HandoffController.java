package com.acme.review.controller;

import com.acme.review.dto.HandoffRequest;
import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.service.ReviewService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
/**
 * 审核交接（Handoff）接口
 * 负责处理审核任务的详情查询与结果提交
 */
@RestController
@RequestMapping("/api/review/handoff")
@RequiredArgsConstructor
public class HandoffController {

    private final ReviewService reviewService;

    /**
     * 获取审核任务详情
     * 
     * @param taskId 任务ID（路径参数）
     * @return 任务详情响应对象，若任务不存在则返回 404
     */
    @GetMapping("/{taskId}")
    public ResponseEntity<TaskDetailResponse> getHandoff(@PathVariable String taskId) {
        return reviewService.getHandoff(taskId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    /**
     * 提交审核交接结果
     * 
     * @param taskId  任务ID（路径参数）
     * @param request 审核交接的请求参数（请求体）
     * @return 更新后的任务详情，若任务不存在则返回 404
     */
    @PostMapping("/{taskId}")
    public ResponseEntity<TaskDetailResponse> submitHandoff(@PathVariable String taskId, @Valid @RequestBody HandoffRequest request) {
        return reviewService.submitHandoff(taskId, request)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
