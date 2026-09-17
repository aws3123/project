package com.acme.review.service;

import com.acme.review.client.PythonComputeClient;
import com.acme.review.entity.IncidentRecordDraft;
import com.acme.review.entity.ReviewResult;
import com.acme.review.entity.ReviewTaskPayload;
import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.IncidentRecordDraftMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskPayloadMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/** 将负反馈和其原始审查上下文固化为只能审核、不能手改的事故草稿。 */
@Service
@RequiredArgsConstructor
public class IncidentRecordService {

    public static final String INCOMPLETE = "INCOMPLETE";
    public static final String PENDING_REVIEW = "PENDING_REVIEW";
    public static final String INGESTING = "INGESTING";
    public static final String APPROVED = "APPROVED";
    public static final String REJECTED = "REJECTED";
    public static final String INGEST_FAILED = "INGEST_FAILED";

    private final IncidentRecordDraftMapper draftMapper;
    private final ReviewTaskPayloadMapper payloadMapper;
    private final ReviewResultMapper resultMapper;
    private final PythonComputeClient pythonComputeClient;
    private final ObjectMapper objectMapper;

    @Transactional
    public IncidentRecordDraft createOrRefreshDraft(UserFeedback feedback) {
        if (!"thumbs_down".equals(feedback.getFeedbackType())) {
            throw new IllegalArgumentException("Only thumbs_down feedback can create an incident draft");
        }
        if (feedback.getId() == null) {
            throw new IllegalStateException("Feedback id is required before creating an incident draft");
        }

        ReviewTaskPayload payload = payloadMapper.findByTaskId(feedback.getTaskId()).orElse(null);
        ReviewResult result = resultMapper.findByTaskId(feedback.getTaskId()).orElse(null);
        IncidentRecordDraft draft = draftMapper.findByFeedbackId(feedback.getId())
                .orElseGet(IncidentRecordDraft::new);

        draft.setFeedbackId(feedback.getId());
        draft.setTaskId(feedback.getTaskId());
        draft.setFeedbackSnapshotJson(toJson(objectMapper.valueToTree(feedback)));
        draft.setAstSnapshotJson(toJson(buildAstSnapshot(payload)));
        draft.setReviewSnapshotJson(toJson(buildReviewSnapshot(result)));
        draft.setIncidentContent(buildIncidentContent(feedback, payload, result));
        if (hasAst(payload) && result != null) {
            if (!APPROVED.equals(draft.getStatus()) && !REJECTED.equals(draft.getStatus())) {
                draft.setStatus(PENDING_REVIEW);
            }
        } else if (draft.getStatus() == null || INCOMPLETE.equals(draft.getStatus())) {
            draft.setStatus(INCOMPLETE);
        }

        if (draft.getId() == null) {
            draft.setCreatedAt(Instant.now());
            draftMapper.insert(draft);
        } else {
            draftMapper.updateById(draft);
        }
        return draft;
    }

    public IPage<IncidentRecordDraft> list(String status, int page, int size) {
        LambdaQueryWrapper<IncidentRecordDraft> wrapper = new LambdaQueryWrapper<IncidentRecordDraft>()
                .orderByDesc(IncidentRecordDraft::getCreatedAt);
        if (status != null && !status.isBlank()) wrapper.eq(IncidentRecordDraft::getStatus, status);
        return draftMapper.selectPage(new Page<>(page, size), wrapper);
    }

    @Transactional
    public IncidentRecordDraft decide(Long id, String decision, String rejectionReason, String reviewer) {
        IncidentRecordDraft draft = draftMapper.selectById(id);
        if (draft == null) throw new IllegalArgumentException("Incident draft not found: " + id);
        String normalized = decision == null ? "" : decision.trim().toLowerCase();
        if ("reject" .equals(normalized)) {
            draft.setStatus(REJECTED);
            draft.setRejectionReason(blankToNull(rejectionReason));
            draft.setReviewer(blankToDefault(reviewer));
            draft.setReviewedAt(Instant.now());
            draftMapper.updateById(draft);
            return draft;
        }
        if (!"approve".equals(normalized)) {
            throw new IllegalArgumentException("decision must be approve or reject");
        }
        if (!PENDING_REVIEW.equals(draft.getStatus()) && !INGEST_FAILED.equals(draft.getStatus())) {
            throw new IllegalStateException("Only ready or failed drafts can be approved; current=" + draft.getStatus());
        }

        draft.setStatus(INGESTING);
        draft.setReviewer(blankToDefault(reviewer));
        draft.setReviewedAt(Instant.now());
        draft.setRejectionReason(null);
        draftMapper.updateById(draft);
        try {
            pythonComputeClient.ingestApprovedIncident(toIngestPayload(draft));
            draft.setStatus(APPROVED);
            draft.setIngestedAt(Instant.now());
            draftMapper.updateById(draft);
            return draft;
        } catch (RuntimeException exc) {
            draft.setStatus(INGEST_FAILED);
            draftMapper.updateById(draft);
            throw exc;
        }
    }

    private ObjectNode buildAstSnapshot(ReviewTaskPayload payload) {
        ObjectNode node = objectMapper.createObjectNode();
        node.set("entities", readJson(payload == null ? null : payload.getEntitiesJson()));
        node.set("relations", readJson(payload == null ? null : payload.getRelationsJson()));
        node.put("diffContent", payload == null || payload.getDiffContent() == null ? "" : payload.getDiffContent());
        return node;
    }

    private ObjectNode buildReviewSnapshot(ReviewResult result) {
        ObjectNode node = objectMapper.createObjectNode();
        if (result == null) return node;
        node.put("riskScore", result.getRiskScore() == null ? null : result.getRiskScore().toPlainString());
        node.put("riskSummary", nullToEmpty(result.getRiskSummary()));
        node.put("needHumanReview", result.isNeedHumanReview());
        node.put("details", nullToEmpty(result.getDetails()));
        node.put("errorCode", nullToEmpty(result.getErrorCode()));
        node.put("errorMessage", nullToEmpty(result.getErrorMessage()));
        return node;
    }

    private JsonNode readJson(String raw) {
        if (raw == null || raw.isBlank()) return objectMapper.createArrayNode();
        try {
            return objectMapper.readTree(raw);
        } catch (Exception ignored) {
            return objectMapper.getNodeFactory().textNode(raw);
        }
    }

    private boolean hasAst(ReviewTaskPayload payload) {
        return payload != null && payload.getEntitiesJson() != null && !payload.getEntitiesJson().isBlank();
    }

    private String buildIncidentContent(UserFeedback feedback, ReviewTaskPayload payload, ReviewResult result) {
        return """
                # 历史事故记录（待人工审核）

                ## 用户反馈
                - 任务：%s
                - 分类：%s
                - 反馈：%s

                ## 审查结果
                - 风险评分：%s
                - 摘要：%s
                - 详情：%s

                ## 请求 AST 与代码变更
                %s
                """.formatted(
                nullToEmpty(feedback.getTaskId()), nullToEmpty(feedback.getCategory()), nullToEmpty(feedback.getComment()),
                result == null || result.getRiskScore() == null ? "" : result.getRiskScore(),
                result == null ? "" : nullToEmpty(result.getRiskSummary()),
                result == null ? "" : truncate(result.getDetails(), 6000),
                payload == null ? "原始 AST 尚未就绪" : truncate(payload.getEntitiesJson(), 8000));
    }

    private Map<String, Object> toIngestPayload(IncidentRecordDraft draft) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("draftId", draft.getId());
        payload.put("feedbackId", draft.getFeedbackId());
        payload.put("taskId", draft.getTaskId());
        payload.put("incidentContent", draft.getIncidentContent());
        payload.put("feedbackSnapshotJson", draft.getFeedbackSnapshotJson());
        payload.put("astSnapshotJson", draft.getAstSnapshotJson());
        payload.put("reviewSnapshotJson", draft.getReviewSnapshotJson());
        return payload;
    }

    private String toJson(JsonNode node) {
        try { return objectMapper.writeValueAsString(node); }
        catch (Exception exc) { throw new IllegalStateException("Failed to serialize incident draft", exc); }
    }
    private String blankToDefault(String value) { return value == null || value.isBlank() ? "MANUAL_REVIEWER" : value; }
    private String blankToNull(String value) { return value == null || value.isBlank() ? null : value; }
    private String nullToEmpty(String value) { return value == null ? "" : value; }
    private String truncate(String value, int max) { return value == null ? "" : value.substring(0, Math.min(value.length(), max)); }
}
