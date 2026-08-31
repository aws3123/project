package com.acme.review.service;

import com.acme.review.dto.DispatchRoute;

public record ReviewDispatchDecision(
        DispatchRoute route,
        String dispatchReason,
        double confidence,
        boolean usedLightweightClassifier
) {
}
