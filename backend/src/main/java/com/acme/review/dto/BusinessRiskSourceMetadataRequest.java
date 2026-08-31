package com.acme.review.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.HashMap;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskSourceMetadataRequest {

    @NotBlank
    private String schemaVersion;

    @NotBlank
    private String projectId;

    @NotBlank
    private String repo;

    @NotBlank
    private String branch;

    private String requestId;

    private String sessionId;

    private String traceId;

    private String entryHint;

    private Map<String, Object> memoryContext = new HashMap<>();

    private String memoryVersion;
}
