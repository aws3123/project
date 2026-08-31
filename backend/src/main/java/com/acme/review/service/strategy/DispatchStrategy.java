package com.acme.review.service.strategy;

import com.acme.review.ast.AstEntity;
import com.acme.review.ast.AstPreprocessedResult;
import com.acme.review.ast.AstRelation;
import com.acme.review.config.OrchestratorProperties;
import com.acme.review.config.ReviewDispatchProperties;
import com.acme.review.dto.DispatchRoute;
import com.acme.review.dto.ReviewAsyncResponse;
import com.acme.review.dto.ReviewDispatchRequest;
import com.acme.review.dto.ReviewDispatchResponse;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.service.ConcurrentMetricsService;
import com.acme.review.service.LightweightRouteClassifier;
import com.acme.review.service.ReviewDispatchDecision;
import com.acme.review.service.ReviewDispatchFeatureExtractor;
import com.acme.review.service.ReviewDispatchFeatures;
import com.acme.review.service.TreeSitterPreprocessService;
import com.acme.review.service.WebhookDedupProperties;
import com.acme.review.service.WebhookDedupService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * 自动路由分发策略。
 * 决策流程：Webhook 去重 → 系统负载检查 → 特征直判 → 分类器决策 → 执行同步或异步。
 */
@Slf4j
@Component("dispatchReviewStrategy")
@RequiredArgsConstructor
public class DispatchStrategy implements ReviewExecutionStrategy {

    private final WebhookDedupService webhookDedupService;
    private final WebhookDedupProperties dedupProps;
    private final ReviewDispatchFeatureExtractor featureExtractor;
    private final LightweightRouteClassifier classifier;
    private final ReviewDispatchProperties dispatchProps;
    private final ThreadPoolExecutor reviewExecutor;
    private final ConcurrentMetricsService metrics;
    private final OrchestratorProperties orchProps;
    private final SyncStrategy syncStrategy;
    private final AsyncStrategy asyncStrategy;
    private final TreeSitterPreprocessService treeSitterPreprocessService;

    /**
     * 智能分发审核任务。
     * 1. Webhook 去重
     * 2. 系统负载检查（队列 > 70% 或活跃线程 > 80% → 强制异步）
     * 3. 特征提取 + 直判（小改动→同步，大改动/高风险→异步）
     * 4. 分类器决策（置信度不足时降级为异步）
     */
    public ReviewDispatchResponse dispatch(ReviewDispatchRequest request) {
        String dedupKey = "webhook:" + request.getProjectId() + ":" + request.getPrUrl().hashCode();
        if (!webhookDedupService.tryAcquire(dedupKey, dedupProps.dedupLockTtlSeconds())) {
            log.info("Duplicate webhook detected key={}", dedupKey);
            ReviewDispatchResponse duplicate = new ReviewDispatchResponse();
            duplicate.setRoute(DispatchRoute.ASYNC);
            duplicate.setStatus("DUPLICATE");
            duplicate.setDispatchReason("duplicate_webhook");
            return duplicate;
        }
        try {
            return doDispatch(request);
        } finally {
            webhookDedupService.release(dedupKey);
        }
    }

    private ReviewDispatchResponse doDispatch(ReviewDispatchRequest request) {
        double queueUsage = (double) reviewExecutor.getQueue().size() / orchProps.queueCapacity();
        int active = metrics.getActiveCount();
        double activeRatio = (double) active / orchProps.maxPoolSize();

        if (queueUsage > 0.7 || activeRatio > 0.8) {
            ReviewSyncRequest syncRequest = toSyncRequest(request);
            syncRequest.setMode(ReviewMode.ASYNC);
            ReviewAsyncResponse asyncResponse = asyncStrategy.publishAsync(syncRequest);
            return ReviewDispatchResponse.fromAsync(
                    new ReviewDispatchDecision(DispatchRoute.ASYNC,
                            queueUsage > 0.7 ? "system_load_high" : "concurrency_high", 1.0, false),
                    asyncResponse);
        }

        ReviewDispatchFeatures features = featureExtractor.extract(request);
        ReviewDispatchDecision direct = directDecision(features);
        if (direct != null) {
            return executeDispatch(request, direct);
        }

        ReviewDispatchDecision classifierDecision = classifier.classify(request, features);
        if (classifierDecision.confidence() < dispatchProps.getClassifierConfidenceThreshold()) {
            classifierDecision = new ReviewDispatchDecision(
                    DispatchRoute.ASYNC, "low_confidence", classifierDecision.confidence(), true);
        }
        return executeDispatch(request, classifierDecision);
    }

    private ReviewDispatchDecision directDecision(ReviewDispatchFeatures features) {
        int smallChars = dispatchProps.getSmallDiffChars();
        int largeChars = dispatchProps.getLargeDiffChars();
        int smallFiles = dispatchProps.getSmallFileCount();
        int largeFiles = dispatchProps.getLargeFileCount();

        if (features.diffChars() <= smallChars
                && features.fileCount() <= smallFiles
                && features.moduleCount() == 1
                && features.riskSignals().isEmpty()
                && features.quickIntent()) {
            return new ReviewDispatchDecision(DispatchRoute.SYNC, "direct_sync_small_simple", 1.0, false);
        }
        if (features.diffChars() >= largeChars
                || features.fileCount() >= largeFiles
                || features.moduleCount() > 1
                || !features.riskSignals().isEmpty()
                || features.deepIntent()) {
            return new ReviewDispatchDecision(DispatchRoute.ASYNC, "direct_async_high_risk", 1.0, false);
        }
        return null;
    }

    private ReviewDispatchResponse executeDispatch(ReviewDispatchRequest request, ReviewDispatchDecision decision) {
        ReviewSyncRequest syncRequest = toSyncRequest(request);
        if (decision.route() == DispatchRoute.SYNC) {
            syncRequest.setMode(ReviewMode.SYNC);
            ReviewSyncResponse result = syncStrategy.executeSync(syncRequest);
            return ReviewDispatchResponse.fromSync(decision, result);
        }
        syncRequest.setMode(ReviewMode.ASYNC);
        ReviewAsyncResponse response = asyncStrategy.publishAsync(syncRequest);
        return ReviewDispatchResponse.fromAsync(decision, response);
    }

    private ReviewSyncRequest toSyncRequest(ReviewDispatchRequest request) {
        ReviewSyncRequest syncRequest = new ReviewSyncRequest();
        syncRequest.setProjectId(request.getProjectId());
        syncRequest.setProjectName(request.getProjectName());
        syncRequest.setPrUrl(request.getPrUrl());
        syncRequest.setDiffContent(request.getDiffContent());
        enrichSyncRequestWithAst(syncRequest);
        return syncRequest;
    }

    private void enrichSyncRequestWithAst(ReviewSyncRequest syncRequest) {
        try {
            AstPreprocessedResult result = treeSitterPreprocessService.preprocess(syncRequest.getDiffContent());
            if (!result.isEmpty()) {
                syncRequest.setEntities(astEntitiesToMap(result.getEntities()));
                syncRequest.setRelations(astRelationsToMap(result.getRelations()));
            }
        } catch (Exception e) {
            log.warn("AST preprocessing in dispatch failed, falling back: {}", e.getMessage());
        }
    }

    private List<Map<String, Object>> astEntitiesToMap(List<AstEntity> entities) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (AstEntity e : entities) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", e.getName());
            m.put("kind", e.getKind());
            m.put("file_path", e.getFilePath());
            m.put("line_start", e.getLineStart());
            m.put("line_end", e.getLineEnd());
            m.put("language", e.getLanguage());
            m.put("modifiers", e.getModifiers());
            m.put("signature", e.getSignature());
            m.put("fully_qualified_name", e.getFullyQualifiedName());
            m.put("parent_class", e.getParentClass());
            m.put("package", e.getPackageName());
            list.add(m);
        }
        return list;
    }

    private List<Map<String, Object>> astRelationsToMap(List<AstRelation> relations) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (AstRelation r : relations) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("source", r.getSource());
            m.put("target", r.getTarget());
            m.put("relation_type", r.getRelationType());
            list.add(m);
        }
        return list;
    }
}
