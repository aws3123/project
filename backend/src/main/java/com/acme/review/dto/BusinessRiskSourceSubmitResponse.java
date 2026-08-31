package com.acme.review.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class BusinessRiskSourceSubmitResponse {
    private String taskId;
    private String status;
    private String streamUrl;
    private String sessionId;
    private String traceId;
}
