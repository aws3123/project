package com.acme.review.controller;

import com.acme.review.service.SseRegistry;
import com.acme.review.service.StreamResumeService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
/**
 * 审核任务通知接口
 * 负责通过 SSE (Server-Sent Events) 向前端实时推送任务状态更新。
 *
 * 重连语义：若请求携带 Last-Event-ID（来自同步流式的最后一条事件 ID），或事件
 * 缓存存在（同步流式任务），优先走 StreamResumeService 做断线补偿（重放 + 尾随）；
 * 否则退回 sseRegistry 注册，保持异步链路行为不变。
 */
@RestController
@RequestMapping("/api/review/tasks")
@RequiredArgsConstructor
public class NotificationController {

    /** 断线重连的 SSE 超时，与同步流式 emitter 兜底超时一致。 */
    private static final long RESUME_EMITTER_TIMEOUT_MS = 180_000L;

    private final SseRegistry sseRegistry;
    private final StreamResumeService streamResumeService;

    /**
     * 建立指定任务的 SSE 实时推送连接
     *
     * @param taskId 任务ID（路径参数）
     * @param lastEventIdHeader 上次最后一条事件 ID（SSE Last-Event-ID 头），用于断线补偿
     * @param lastEventIdParam 与 lastEventIdHeader 等价的查询参数（fetch 流式读场景）
     * @return SSE 连接发射器 (SseEmitter)，用于向客户端持续发送事件流
     */
    @GetMapping(value = "/{taskId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamTask(@PathVariable String taskId,
                                 @RequestHeader(value = "Last-Event-ID", required = false) String lastEventIdHeader,
                                 @RequestParam(value = "lastEventId", required = false) String lastEventIdParam) {
        String lastEventId = (lastEventIdParam != null && !lastEventIdParam.isBlank())
                ? lastEventIdParam
                : lastEventIdHeader;

        boolean hasAnchor = lastEventId != null && !lastEventId.isBlank();
        if (hasAnchor || streamResumeService.hasCachedStream(taskId)) {
            SseEmitter emitter = new SseEmitter(RESUME_EMITTER_TIMEOUT_MS);
            if (streamResumeService.tryResume(taskId, lastEventId, emitter)) {
                return emitter;
            }
        }
        return sseRegistry.register(taskId);
    }
}
