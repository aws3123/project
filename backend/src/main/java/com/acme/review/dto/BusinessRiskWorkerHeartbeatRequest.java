package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskWorkerHeartbeatRequest {

    @JsonProperty("instance_id")
    private String instanceId;

    @JsonProperty("worker_version")
    private String workerVersion;

    @JsonProperty("started_at")
    private Instant startedAt;

    @JsonProperty("schema_versions_supported")
    private List<String> schemaVersionsSupported = new ArrayList<>();

    @JsonProperty("java_preprocess_versions_supported")
    private List<String> javaPreprocessVersionsSupported = new ArrayList<>();

    private String readiness;

    @JsonProperty("inflight_count")
    private int inflightCount;

    @JsonProperty("max_concurrency")
    private int maxConcurrency;

    @JsonProperty("last_error")
    private String lastError;
}
