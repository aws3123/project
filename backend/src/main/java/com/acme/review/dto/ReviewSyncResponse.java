package com.acme.review.dto;

import java.util.List;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ReviewSyncResponse {

    private String taskId;
    private double riskScore;
    private String riskSummary;
    private boolean needHumanReview;
    private List<String> details;
}
