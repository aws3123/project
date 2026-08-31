package com.acme.review.entity;

import lombok.Getter;

import java.util.Arrays;

@Getter
public enum ReviewTaskStatus {
    /**
     * 待处理 / 等待中
     */
    PENDING("pending"),

    /**
     * 处理中
     */
    PROCESSING("processing"),

    /**
     * 处理成功
     */
    SUCCESS("success"),

    /**
     * 处理失败
     */
    FAILED("failed"),

    /**
     * 需要人工审核 / 人工介入
     */
    HUMAN_REVIEW("human_review");

    private final String dbValue;

    ReviewTaskStatus(String dbValue) {
        this.dbValue = dbValue;
    }

    public static ReviewTaskStatus fromDbValue(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return Arrays.stream(values())
                .filter(status -> status.dbValue.equalsIgnoreCase(value) || status.name().equalsIgnoreCase(value))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Unknown ReviewTaskStatus value: " + value));
    }

    public boolean isTerminal() {
        return this == SUCCESS || this == FAILED || this == HUMAN_REVIEW;
    }
}
