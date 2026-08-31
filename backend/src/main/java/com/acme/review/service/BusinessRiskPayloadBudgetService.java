package com.acme.review.service;

import com.acme.review.dto.BusinessRiskAnalysisHints;
import com.acme.review.dto.BusinessRiskBudgetDecision;
import com.acme.review.dto.BusinessRiskPreparedHotspot;
import com.acme.review.dto.BusinessRiskPreparedMethod;
import com.acme.review.dto.BusinessRiskPreparedSourceFile;
import com.acme.review.dto.BusinessRiskSourcePackage;
import com.acme.review.exception.BusinessRiskPreprocessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class BusinessRiskPayloadBudgetService {

    private final ObjectMapper objectMapper;

    @Value("${business-risk.source.max-prepared-bytes:262144}")
    private long maxPreparedBytes;

    @Value("${business-risk.source.trim-to-bytes:196608}")
    private long trimToBytes;

    public BusinessRiskBudgetDecision applyBudget(BusinessRiskSourcePackage sourcePackage, BusinessRiskAnalysisHints analysisHints, long rawTotalBytes) {
        BusinessRiskBudgetDecision decision = new BusinessRiskBudgetDecision();
        decision.setRawTotalBytes(rawTotalBytes);

        long preparedBytes = estimateBytes(sourcePackage, analysisHints);
        decision.setPreparedTotalBytes(preparedBytes);
        if (preparedBytes <= maxPreparedBytes) {
            decision.setDecision("ACCEPT_AS_IS");
            return decision;
        }

        trimSnippets(sourcePackage);
        preparedBytes = estimateBytes(sourcePackage, analysisHints);
        if (preparedBytes > trimToBytes) {
            dropLowPriorityMethods(sourcePackage, decision);
            syncAnalysisHints(sourcePackage, analysisHints);
            preparedBytes = estimateBytes(sourcePackage, analysisHints);
        }
        if (preparedBytes > trimToBytes) {
            dropLowPriorityHotspots(sourcePackage, decision);
            syncAnalysisHints(sourcePackage, analysisHints);
            preparedBytes = estimateBytes(sourcePackage, analysisHints);
        }
        if (preparedBytes > trimToBytes) {
            dropLowPriorityFiles(sourcePackage, decision);
            syncAnalysisHints(sourcePackage, analysisHints);
            preparedBytes = estimateBytes(sourcePackage, analysisHints);
        }

        decision.setPreparedTotalBytes(preparedBytes);
        if (preparedBytes <= maxPreparedBytes) {
            decision.setDecision("TRIMMED");
            return decision;
        }

        decision.setDecision("REJECTED");
        throw new BusinessRiskPreprocessException(
                "SOURCE_PREPROCESS_BUDGET_EXCEEDED",
                "Prepared payload exceeds budget after trim: " + preparedBytes + " bytes"
        );
    }

    private void trimSnippets(BusinessRiskSourcePackage sourcePackage) {
        for (BusinessRiskPreparedSourceFile file : sourcePackage.getFiles()) {
            for (BusinessRiskPreparedMethod method : file.getMethods()) {
                method.setSnippet(limit(method.getSnippet(), 600));
            }
            for (BusinessRiskPreparedHotspot hotspot : file.getHotspots()) {
                hotspot.setSnippet(limit(hotspot.getSnippet(), 400));
            }
        }
    }

    private void dropLowPriorityMethods(BusinessRiskSourcePackage sourcePackage, BusinessRiskBudgetDecision decision) {
        for (BusinessRiskPreparedSourceFile file : sourcePackage.getFiles()) {
            Iterator<BusinessRiskPreparedMethod> iterator = file.getMethods().iterator();
            while (iterator.hasNext()) {
                BusinessRiskPreparedMethod method = iterator.next();
                if (isHighPriority(method)) {
                    continue;
                }
                decision.getDroppedMethods().add(file.getPath() + "#" + method.getMethodId());
                iterator.remove();
                if (estimateBytes(sourcePackage) <= trimToBytes) {
                    return;
                }
            }
        }
    }

    private void dropLowPriorityHotspots(BusinessRiskSourcePackage sourcePackage, BusinessRiskBudgetDecision decision) {
        for (BusinessRiskPreparedSourceFile file : sourcePackage.getFiles()) {
            Iterator<BusinessRiskPreparedHotspot> iterator = file.getHotspots().iterator();
            while (iterator.hasNext()) {
                BusinessRiskPreparedHotspot hotspot = iterator.next();
                if (isHighPriority(hotspot)) {
                    continue;
                }
                decision.getDroppedHotspots().add(file.getPath() + "#" + hotspot.getMethodId());
                iterator.remove();
                if (estimateBytes(sourcePackage) <= trimToBytes) {
                    return;
                }
            }
        }
    }

    private void dropLowPriorityFiles(BusinessRiskSourcePackage sourcePackage, BusinessRiskBudgetDecision decision) {
        Iterator<BusinessRiskPreparedSourceFile> iterator = sourcePackage.getFiles().iterator();
        while (iterator.hasNext()) {
            BusinessRiskPreparedSourceFile file = iterator.next();
            if (!file.getHotspots().isEmpty() || !file.getRepositoryDependencies().isEmpty()) {
                continue;
            }
            decision.getDroppedFiles().add(file.getPath());
            iterator.remove();
            if (estimateBytes(sourcePackage) <= trimToBytes) {
                break;
            }
        }
        sourcePackage.setFileCount(sourcePackage.getFiles().size());
    }

    private boolean isHighPriority(BusinessRiskPreparedMethod method) {
        if ("TRANSACTIONAL".equalsIgnoreCase(method.getTransactionBoundary())) {
            return true;
        }
        if (method.getLockSemantics() != null && !method.getLockSemantics().isEmpty()) {
            return true;
        }
        if (method.getKeyCalls() == null) {
            return false;
        }
        for (String keyCall : method.getKeyCalls()) {
            String normalized = keyCall.toLowerCase();
            if (normalized.contains("repository")
                    || normalized.contains("inventory")
                    || normalized.contains("order")
                    || normalized.contains("cache")
                    || normalized.contains("mq")
                    || normalized.contains("client")) {
                return true;
            }
        }
        return false;
    }

    private boolean isHighPriority(BusinessRiskPreparedHotspot hotspot) {
        if (hotspot.getRiskTags() == null || hotspot.getRiskTags().isEmpty()) {
            return false;
        }
        for (String riskTag : hotspot.getRiskTags()) {
            if (!"INFO".equalsIgnoreCase(riskTag)) {
                return true;
            }
        }
        return false;
    }

    private long estimateBytes(BusinessRiskSourcePackage sourcePackage, BusinessRiskAnalysisHints analysisHints) {
        try {
            return objectMapper.writeValueAsBytes(Map.of(
                    "source_package", sourcePackage == null ? Map.of() : sourcePackage,
                    "analysis_hints", analysisHints == null ? Map.of() : analysisHints
            )).length;
        } catch (Exception ex) {
            throw new BusinessRiskPreprocessException("SOURCE_PREPROCESS_FAILED", "Failed to estimate prepared payload size", ex);
        }
    }

    private long estimateBytes(BusinessRiskSourcePackage sourcePackage) {
        return estimateBytes(sourcePackage, null);
    }

    private void syncAnalysisHints(BusinessRiskSourcePackage sourcePackage, BusinessRiskAnalysisHints analysisHints) {
        if (sourcePackage == null || analysisHints == null) {
            return;
        }

        Set<String> remainingMethodIds = new LinkedHashSet<>();
        Set<String> remainingHotspotMethodIds = new LinkedHashSet<>();
        Set<String> remainingRiskTypes = new LinkedHashSet<>();
        for (BusinessRiskPreparedSourceFile file : sourcePackage.getFiles()) {
            for (BusinessRiskPreparedMethod method : file.getMethods()) {
                remainingMethodIds.add(method.getMethodId());
            }
            for (BusinessRiskPreparedHotspot hotspot : file.getHotspots()) {
                remainingHotspotMethodIds.add(hotspot.getMethodId());
                if (hotspot.getRiskTags() != null) {
                    remainingRiskTypes.addAll(hotspot.getRiskTags());
                }
            }
        }

        analysisHints.setFocusMethods(filterExisting(analysisHints.getFocusMethods(), remainingMethodIds));
        analysisHints.setFocusCallPaths(filterExisting(analysisHints.getFocusCallPaths(), remainingMethodIds));
        analysisHints.setHotspotMethodIds(filterExisting(analysisHints.getHotspotMethodIds(), remainingHotspotMethodIds));
        analysisHints.setCandidateRiskTypes(filterExisting(analysisHints.getCandidateRiskTypes(), remainingRiskTypes));
    }

    private List<String> filterExisting(List<String> values, Set<String> allowed) {
        List<String> filtered = new ArrayList<>();
        if (values == null || allowed == null || allowed.isEmpty()) {
            return filtered;
        }
        for (String value : values) {
            if (value != null && allowed.contains(value)) {
                filtered.add(value);
            }
        }
        return filtered;
    }

    private String limit(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, Math.max(0, maxLength - 3)) + "...";
    }
}
