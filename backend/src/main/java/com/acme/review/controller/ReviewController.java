package com.acme.review.controller;

import com.acme.review.ast.AstEntity;
import com.acme.review.ast.AstPreprocessedResult;
import com.acme.review.ast.AstRelation;
import com.acme.review.dto.ReviewAsyncResponse;
import com.acme.review.client.PythonComputeClient;
import com.acme.review.dto.ReviewDispatchRequest;
import com.acme.review.dto.ReviewDispatchResponse;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.service.TreeSitterPreprocessService;
import com.acme.review.service.strategy.ReviewStrategyFactory;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import lombok.extern.slf4j.Slf4j;

/**
 * 审核业务核心接口
 * 负责处理同步/异步/自动路由审核任务的触发与任务分发
 */
@RestController
@RequestMapping("/api/review")
@Validated
@RequiredArgsConstructor
@Slf4j
public class ReviewController {

    private final ReviewStrategyFactory reviewStrategyFactory;
    private final PythonComputeClient pythonComputeClient;
    private final TreeSitterPreprocessService treeSitterPreprocessService;

    /**
     * 触发同步审核任务
     * 接口会阻塞等待审核流程全部执行完毕后，直接返回完整的审核结果
     *
     * @param request 审核同步请求参数（必须指定 mode 为 SYNC）
     * @return 包含审核结果的响应对象
     */
    @PostMapping("/sync")
    public ResponseEntity<ReviewSyncResponse> runSyncReview(@Valid @RequestBody ReviewSyncRequest request) {
        if (request.getMode() != ReviewMode.SYNC) {
            throw new IllegalArgumentException("Only SYNC mode is supported in this endpoint");
        }
        enrichRequestWithAst(request);
        ReviewSyncResponse response = reviewStrategyFactory.getSyncStrategy().executeSync(request);
        return ResponseEntity.ok(response);
    }

    /**
     * 触发异步审核任务
     * 接口接收请求后立即返回任务受理信息（如任务ID），后台异步执行审核流程
     *
     * @param request 审核异步请求参数（必须指定 mode 为 ASYNC）
     * @return 包含任务受理信息的响应对象，HTTP 状态码为 202 Accepted
     */
    @PostMapping("/async")
    public ResponseEntity<ReviewAsyncResponse> runAsyncReview(@Valid @RequestBody ReviewSyncRequest request) {
        if (request.getMode() != ReviewMode.ASYNC) {
            throw new IllegalArgumentException("Only ASYNC mode is supported in this endpoint");
        }
        enrichRequestWithAst(request);
        ReviewAsyncResponse response = reviewStrategyFactory.getAsyncStrategy().publishAsync(request);
        return ResponseEntity.accepted().body(response);
    }

    private void enrichRequestWithAst(ReviewSyncRequest request) {
        if (request.getEntities() != null || request.getRelations() != null) {
            return;
        }
        try {
            AstPreprocessedResult result = treeSitterPreprocessService.preprocess(request.getDiffContent());
            request.setEntities(astEntitiesToMap(result.getEntities()));
            request.setRelations(astRelationsToMap(result.getRelations()));
        } catch (Exception e) {
            log.warn("AST preprocessing failed, falling back to raw diff: {}", e.getMessage());
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

    /**
     * 审核任务分发
     * 将待审核的任务按照既定规则分发给对应的审核人员或审核系统
     * 
     * @param request 任务分发请求参数
     * @return 分发结果的响应对象
     */
    @PostMapping("/dispatch")
    public ResponseEntity<ReviewDispatchResponse> dispatchReview(@Valid @RequestBody ReviewDispatchRequest request) {
        return ResponseEntity.ok(reviewStrategyFactory.getDispatchStrategy().dispatch(request));
    }

    @GetMapping("/logs/{taskId}")
    public ResponseEntity<List<Map<String, Object>>> getLogs(@PathVariable String taskId) {
        List<Map<String, Object>> logs = pythonComputeClient.fetchLogs(taskId);
        return ResponseEntity.ok(logs);
    }
}
