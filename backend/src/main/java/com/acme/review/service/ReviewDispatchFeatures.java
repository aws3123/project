package com.acme.review.service;

import java.util.Set;

public record ReviewDispatchFeatures(
        int diffChars,
        int fileCount,
        int moduleCount,
        Set<String> riskSignals,
        boolean quickIntent,
        boolean deepIntent
) {
}
