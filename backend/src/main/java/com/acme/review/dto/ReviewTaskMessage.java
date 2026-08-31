package com.acme.review.dto;

import java.util.List;
import java.util.Map;

public class ReviewTaskMessage {
    private String taskId;
    private String projectId;
    private String projectName;
    private String prUrl;
    private String diffContent;
    private String traceId;
    private String mode;
    private List<Map<String, Object>> entities;
    private List<Map<String, Object>> relations;

    public ReviewTaskMessage() {}

    public ReviewTaskMessage(String taskId, String projectId, String projectName, String prUrl,
                             String diffContent, String traceId, String mode,
                             List<Map<String, Object>> entities, List<Map<String, Object>> relations) {
        this.taskId = taskId;
        this.projectId = projectId;
        this.projectName = projectName;
        this.prUrl = prUrl;
        this.diffContent = diffContent;
        this.traceId = traceId;
        this.mode = mode;
        this.entities = entities;
        this.relations = relations;
    }

    public String getTaskId() { return taskId; }
    public void setTaskId(String taskId) { this.taskId = taskId; }

    public String getProjectId() { return projectId; }
    public void setProjectId(String projectId) { this.projectId = projectId; }

    public String getProjectName() { return projectName; }
    public void setProjectName(String projectName) { this.projectName = projectName; }

    public String getPrUrl() { return prUrl; }
    public void setPrUrl(String prUrl) { this.prUrl = prUrl; }

    public String getDiffContent() { return diffContent; }
    public void setDiffContent(String diffContent) { this.diffContent = diffContent; }

    public String getTraceId() { return traceId; }
    public void setTraceId(String traceId) { this.traceId = traceId; }

    public String getMode() { return mode; }
    public void setMode(String mode) { this.mode = mode; }

    public List<Map<String, Object>> getEntities() { return entities; }
    public void setEntities(List<Map<String, Object>> entities) { this.entities = entities; }

    public List<Map<String, Object>> getRelations() { return relations; }
    public void setRelations(List<Map<String, Object>> relations) { this.relations = relations; }
}
