package com.acme.review.controller;

import com.acme.review.service.SseRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
/**
 * 审核任务通知接口
 * 负责通过 SSE (Server-Sent Events) 向前端实时推送任务状态更新
 */
@RestController
@RequestMapping("/api/review/tasks")
@RequiredArgsConstructor
public class NotificationController {

    private final SseRegistry sseRegistry;

    /**
     * 建立指定任务的 SSE 实时推送连接
     * 
     * @param taskId 任务ID（路径参数）
     * @return SSE 连接发射器 (SseEmitter)，用于向客户端持续发送事件流
     */
    @GetMapping(value = "/{taskId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamTask(@PathVariable String taskId) {
        return sseRegistry.register(taskId);
    }
}
