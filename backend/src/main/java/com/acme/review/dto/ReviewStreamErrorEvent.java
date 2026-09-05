package com.acme.review.dto;

/**
 * Python 流式同步审查的 run_error 终态事件载荷。
 */
public record ReviewStreamErrorEvent(String taskId, String errorCode, String errorMessage) {
}
