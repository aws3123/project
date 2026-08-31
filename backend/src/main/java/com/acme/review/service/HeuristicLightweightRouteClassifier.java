package com.acme.review.service;

import com.acme.review.dto.DispatchRoute;
import com.acme.review.dto.ReviewDispatchRequest;
import org.springframework.stereotype.Component;

@Component
public class HeuristicLightweightRouteClassifier implements LightweightRouteClassifier {
    @Override
    public ReviewDispatchDecision classify(ReviewDispatchRequest request, ReviewDispatchFeatures features) {
        double syncScore = 0;
        double asyncScore = 0;

        if (features.quickIntent()) {
            syncScore += 2;
        }
        if (features.deepIntent()) {
            asyncScore += 2;
        }
        if (features.fileCount() <= 3) {
            syncScore += 1;
        }
        if (features.fileCount() >= 4) {
            asyncScore += 1;
        }
        if (features.moduleCount() > 1) {
            asyncScore += 1.5;
        }
        if (!features.riskSignals().isEmpty()) {
            asyncScore += 2;
        }

        double total = syncScore + asyncScore;
        double confidence = total == 0 ? 0.5 : Math.abs(asyncScore - syncScore) / total;
        DispatchRoute route = asyncScore >= syncScore ? DispatchRoute.ASYNC : DispatchRoute.SYNC;
        String reason = route == DispatchRoute.ASYNC ? "lightweight_classifier_async" : "lightweight_classifier_sync";
        return new ReviewDispatchDecision(route, reason, confidence, true);
    }
}
