package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.HashMap;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskPythonSourceResponse {

    @JsonProperty("run_id")
    private String runId;

    @JsonProperty("task_id")
    private String taskId;

    private String status;

    private Map<String, Object> report = new HashMap<>();

    @JsonProperty("proposed_memory_updates")
    private Map<String, Object> proposedMemoryUpdates = new HashMap<>();

    @JsonProperty("trace_id")
    private String traceId;
}
