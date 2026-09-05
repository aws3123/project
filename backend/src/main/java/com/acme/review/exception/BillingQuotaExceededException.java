package com.acme.review.exception;

/**
 * 计费配额超限异常：调用方累计 token 消耗达到上限时拒绝新任务提交。
 */
public class BillingQuotaExceededException extends RuntimeException {

    private final String submitter;
    private final long usedTokens;
    private final long maxTokens;

    public BillingQuotaExceededException(String submitter, long usedTokens, long maxTokens) {
        super("Billing quota exceeded for submitter=" + submitter
                + " used=" + usedTokens + " max=" + maxTokens);
        this.submitter = submitter;
        this.usedTokens = usedTokens;
        this.maxTokens = maxTokens;
    }

    public String getSubmitter() {
        return submitter;
    }

    public long getUsedTokens() {
        return usedTokens;
    }

    public long getMaxTokens() {
        return maxTokens;
    }
}
