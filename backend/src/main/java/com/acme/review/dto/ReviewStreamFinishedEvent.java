package com.acme.review.dto;

/**
 * Python 流式同步审查的 run_finished 终态事件载荷。
 * result 与旧同步接口的响应契约完全一致。
 */
public record ReviewStreamFinishedEvent(String taskId, ReviewSyncResponse result) {
}
