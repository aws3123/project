package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskCallbackRequest {

    @JsonProperty("run_id")
    private String runId;

    @JsonProperty("task_id")
    private String taskId;

    @JsonProperty("session_id")
    private String sessionId;

    private Boolean success;

    private String status;

    @JsonProperty("risk_summary")
    private String riskSummary;

    @JsonProperty("risk_score")
    private BigDecimal riskScore;

    private Map<String, Object> report = new HashMap<>();

    @JsonProperty("proposed_memory_updates")
    private Map<String, Object> proposedMemoryUpdates = new HashMap<>();

    @JsonProperty("error_code")
    private String errorCode;

    @JsonProperty("error_message")
    private String errorMessage;

    @JsonProperty("trace_id")
    private String traceId;

    public String resolvedTaskId() {
        if (taskId != null && !taskId.isBlank()) {
            return taskId;
        }
        if (runId != null && !runId.isBlank()) {
            return runId;
        }
        return null;
    }
}
