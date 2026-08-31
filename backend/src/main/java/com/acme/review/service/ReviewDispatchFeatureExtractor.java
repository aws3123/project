package com.acme.review.service;

import com.acme.review.config.ReviewDispatchProperties;
import com.acme.review.dto.ReviewDispatchRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Component
@RequiredArgsConstructor
public class ReviewDispatchFeatureExtractor {

    private static final Pattern FILE_PATTERN = Pattern.compile("^diff --git ", Pattern.MULTILINE);
    private final ReviewDispatchProperties properties;

    public ReviewDispatchFeatures extract(ReviewDispatchRequest request) {
        String diff = request.getDiffContent();
        int fileCount = Math.max(1, countMatches(FILE_PATTERN.matcher(diff)));
        Set<String> modules = new LinkedHashSet<>();
        if (diff.contains("frontend/")) {
            modules.add("frontend");
        }
        if (diff.contains("backend/")) {
            modules.add("backend");
        }
        if (diff.contains("application")) {
            modules.add("config");
        }
        if (diff.toLowerCase(Locale.ROOT).contains("sql")) {
            modules.add("sql");
        }

        Set<String> riskSignals = new LinkedHashSet<>();
        String diffUpper = diff.toUpperCase(Locale.ROOT);
        for (String keyword : properties.getHighRiskKeywords()) {
            if (diffUpper.contains(keyword.toUpperCase(Locale.ROOT))) {
                riskSignals.add(keyword);
            }
        }

        String question = request.getQuestion();
        boolean quickIntent = containsAny(question, properties.getQuickIntentKeywords());
        boolean deepIntent = containsAny(question, properties.getDeepIntentKeywords());

        return new ReviewDispatchFeatures(diff.length(), fileCount, modules.size(), riskSignals, quickIntent, deepIntent);
    }

    private static int countMatches(Matcher matcher) {
        int count = 0;
        while (matcher.find()) {
            count++;
        }
        return count;
    }

    private static boolean containsAny(String text, Iterable<String> keywords) {
        if (text == null) {
            return false;
        }
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }
}
