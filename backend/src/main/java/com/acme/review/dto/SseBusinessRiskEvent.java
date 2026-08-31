package com.acme.review.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class SseBusinessRiskEvent {
    private String eventId;
    private String sessionId;
    private String taskId;
    private String type;
    private String payload;
}
