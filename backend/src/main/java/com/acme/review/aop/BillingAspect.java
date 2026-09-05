package com.acme.review.aop;

import com.acme.review.config.BillingProperties;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.exception.BillingQuotaExceededException;
import com.acme.review.service.TokenUsageService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * 计费 AOP 切面：拦截审查任务提交入口，做前置准入（配额）检查。
 *
 * <p><b>设计边界</b>：真实 token 用量产生在 Python 层 LLM 调用（Java 方法边界之外），
 * 因此本切面只做"准入预检"，不做"计量"——计量由 Python metering + RESULT 回调落库。
 * 拦截 Controller 层可拿到类型化的 {@link ReviewSyncRequest}，比 Filter 更直接地
 * 提取业务字段（submitter），这是 AOP 相比 Filter 在此处的实质优势。</p>
 *
 * <p>不传 submitter 的请求不做配额拦截（仅统计时归属空串），保证对存量调用零侵入。</p>
 */
@Aspect
@Component
@Slf4j
@RequiredArgsConstructor
public class BillingAspect {

    private final TokenUsageService tokenUsageService;
    private final BillingProperties billingProperties;

    /** 拦截 ReviewController 所有 run* 提交入口（sync / sync/stream / async） */
    @Around("execution(* com.acme.review.controller.ReviewController.run*(..))")
    public Object enforceQuota(ProceedingJoinPoint pjp) throws Throwable {
        if (!billingProperties.enabled()) {
            return pjp.proceed();
        }
        String submitter = resolveSubmitter(pjp.getArgs());
        if (submitter == null || submitter.isBlank()) {
            return pjp.proceed();
        }
        long used = tokenUsageService.sumTokensBySubmitter(submitter);
        long max = billingProperties.maxTokensPerSubmitter();
        if (used >= max) {
            log.warn("Billing quota exceeded submitter={} used={} max={}", submitter, used, max);
            throw new BillingQuotaExceededException(submitter, used, max);
        }
        return pjp.proceed();
    }

    private String resolveSubmitter(Object[] args) {
        for (Object arg : args) {
            if (arg instanceof ReviewSyncRequest request) {
                return request.getSubmitter();
            }
        }
        return null;
    }
}
