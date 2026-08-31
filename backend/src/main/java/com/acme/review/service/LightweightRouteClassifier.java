package com.acme.review.service;

import com.acme.review.dto.ReviewDispatchRequest;

public interface LightweightRouteClassifier {
    ReviewDispatchDecision classify(ReviewDispatchRequest request, ReviewDispatchFeatures features);
}
