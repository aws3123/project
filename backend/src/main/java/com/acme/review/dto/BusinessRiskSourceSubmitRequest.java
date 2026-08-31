package com.acme.review.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskSourceSubmitRequest {

    @NotBlank
    private String schemaVersion;

    @NotBlank
    private String javaPreprocessVersion;

    @NotBlank
    private String projectId;

    @NotBlank
    private String repo;

    @NotBlank
    private String branch;

    private String requestId;

    private String sessionId;

    private String traceId;

    @Valid
    private BusinessRiskSourceBundle sourceBundle;
}
