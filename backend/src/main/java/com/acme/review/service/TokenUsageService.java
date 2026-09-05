package com.acme.review.service;

import com.acme.review.config.BillingProperties;
import com.acme.review.dto.ReviewCallbackMessage;
import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.TokenUsageRecord;
import com.acme.review.repository.mapper.TokenUsageRecordMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * Token 用量计费服务。
 *
 * <p>数据源是 Python 层 LLM 响应的真实 usage（随 RESULT 回调携带），
 * 单价取配置快照落库，保证历史账目不随调价漂移。本服务只负责记账，
 * 不做请求期计量（请求期计量在 Python 侧、Java AOP 只做准入预检）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TokenUsageService {

    private static final BigDecimal PER_K = BigDecimal.valueOf(1000);

    private final TokenUsageRecordMapper usageMapper;
    private final BillingProperties billingProperties;

    /**
     * 为一次任务记账。usage 缺失或总量为 0 时跳过（无 LLM 调用）。
     *
     * @param task  已落库的审查任务（提供 taskId 与计费归属 submitter）
     * @param usage RESULT 回调携带的真实用量
     */
    public void record(ReviewTask task, ReviewCallbackMessage.Usage usage) {
        if (usage == null) {
            return;
        }
        int total = resolveTotal(usage);
        if (total <= 0) {
            return;
        }
        BigDecimal unitPrice = billingProperties.unitPricePerK();
        BigDecimal cost = unitPrice.multiply(BigDecimal.valueOf(total))
                .divide(PER_K, 6, RoundingMode.HALF_UP);

        TokenUsageRecord record = new TokenUsageRecord();
        record.setTaskId(task.getTaskId());
        record.setSubmitter(task.getSubmitter() != null ? task.getSubmitter() : "");
        record.setModel(usage.getModel());
        record.setPromptTokens(nz(usage.getPromptTokens()));
        record.setCompletionTokens(nz(usage.getCompletionTokens()));
        record.setTotalTokens(total);
        record.setUnitPriceSnapshot(unitPrice);
        record.setCostAmount(cost);
        usageMapper.insert(record);

        log.info("Token usage recorded taskId={} submitter={} total={} cost={}",
                task.getTaskId(), record.getSubmitter(), total, cost.toPlainString());
    }

    /** 查询调用方累计消耗 token 数（准入预检用）。 */
    public long sumTokensBySubmitter(String submitter) {
        if (submitter == null || submitter.isBlank()) {
            return 0;
        }
        return usageMapper.selectList(
                        new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<TokenUsageRecord>()
                                .eq(TokenUsageRecord::getSubmitter, submitter)
                ).stream()
                .mapToLong(r -> r.getTotalTokens() == null ? 0L : r.getTotalTokens())
                .sum();
    }

    private int resolveTotal(ReviewCallbackMessage.Usage usage) {
        if (usage.getTotalTokens() != null && usage.getTotalTokens() > 0) {
            return usage.getTotalTokens();
        }
        return nz(usage.getPromptTokens()) + nz(usage.getCompletionTokens());
    }

    private static int nz(Integer value) {
        return value != null && value > 0 ? value : 0;
    }
}
