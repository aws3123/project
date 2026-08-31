package com.acme.review.dto;

import com.acme.review.service.ReviewDispatchDecision;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class ReviewDispatchResponse {
    private DispatchRoute route;
    private String taskId;
    private String status;
    private String dispatchReason;
    private double confidence;
    private boolean usedLightweightClassifier;
    private ReviewSyncResponse result;

    public static ReviewDispatchResponse fromSync(ReviewDispatchDecision decision, ReviewSyncResponse result) {
        ReviewDispatchResponse response = new ReviewDispatchResponse();
        response.setRoute(DispatchRoute.SYNC);
        response.setTaskId(result.getTaskId());
        response.setStatus("SUCCESS");
        response.setDispatchReason(decision.dispatchReason());
        response.setConfidence(decision.confidence());
        response.setUsedLightweightClassifier(decision.usedLightweightClassifier());
        response.setResult(result);
        return response;
    }

    public static ReviewDispatchResponse fromAsync(ReviewDispatchDecision decision, ReviewAsyncResponse response) {
        ReviewDispatchResponse dispatchResponse = new ReviewDispatchResponse();
        dispatchResponse.setRoute(DispatchRoute.ASYNC);
        dispatchResponse.setTaskId(response.getTaskId());
        dispatchResponse.setStatus(response.getStatus());
        dispatchResponse.setDispatchReason(decision.dispatchReason());
        dispatchResponse.setConfidence(decision.confidence());
        dispatchResponse.setUsedLightweightClassifier(decision.usedLightweightClassifier());
        return dispatchResponse;
    }
}
