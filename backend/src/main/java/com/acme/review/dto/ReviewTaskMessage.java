package com.acme.review.dto;

/**
 * Topic 1 任务下发消息（瘦身后）—— Java 生产 → Python 消费。
 *
 * <p>仅携带 taskId 与小字段，diffContent / entities / relations 等大 payload
 * 落库于 {@code review_task_payload} 表，Python 消费后经内部端点回源拉取，
 * 避免 Kafka 大消息（1MB 上限）问题。</p>
 */
public class ReviewTaskMessage {
    private String taskId;
    private String projectId;
    private String projectName;
    private String prUrl;
    private String traceId;
    private String sessionId;
    private String mode;

    public ReviewTaskMessage() {}

    public ReviewTaskMessage(String taskId, String projectId, String projectName, String prUrl,
                             String traceId, String sessionId, String mode) {
        this.taskId = taskId;
        this.projectId = projectId;
        this.projectName = projectName;
        this.prUrl = prUrl;
        this.traceId = traceId;
        this.sessionId = sessionId;
        this.mode = mode;
    }

    public String getTaskId() { return taskId; }
    public void setTaskId(String taskId) { this.taskId = taskId; }

    public String getProjectId() { return projectId; }
    public void setProjectId(String projectId) { this.projectId = projectId; }

    public String getProjectName() { return projectName; }
    public void setProjectName(String projectName) { this.projectName = projectName; }

    public String getPrUrl() { return prUrl; }
    public void setPrUrl(String prUrl) { this.prUrl = prUrl; }

    public String getTraceId() { return traceId; }
    public void setTraceId(String traceId) { this.traceId = traceId; }

    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }

    public String getMode() { return mode; }
    public void setMode(String mode) { this.mode = mode; }
}
