package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;

/**
 * Topic 2 回调消息 —— Python 处理后回投事件给 Java 状态机。
 *
 * <p>事件类型（eventType）三种，Java 消费端据此分流：</p>
 * <ul>
 *   <li>PROCESSING：Python 消费到任务、开始处理（驱动 PENDING → PROCESSING + SSE）</li>
 *   <li>RESULT：处理完成（携带审查结果，驱动 PROCESSING → SUCCESS / HUMAN_REVIEW）</li>
 *   <li>DEAD_LETTER：永久失败或瞬时失败重试耗尽（驱动 → FAILED）</li>
 * </ul>
 */
@Getter
@Setter
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class ReviewCallbackMessage {

    /** 回调消息唯一 ID（Python 端按 taskId-eventType 生成，Java 端做幂等） */
    private String messageId;

    private String eventType;

    private String taskId;

    private String sessionId;

    private String traceId;

    /** 仅 RESULT 事件携带 */
    private CallbackResult result;

    /** 仅 DEAD_LETTER 事件携带 */
    private String errorCode;

    /** 仅 DEAD_LETTER 事件携带 */
    private String errorMessage;

    @Getter
    @Setter
    @NoArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class CallbackResult {
        private String taskId;
        private String status;
        private double riskScore;
        private String riskSummary;
        private boolean needHumanReview;
        private List<String> details;
    }
}
