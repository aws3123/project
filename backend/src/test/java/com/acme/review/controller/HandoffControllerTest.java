package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.HandoffDecision;
import com.acme.review.dto.HandoffRequest;
import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ReviewService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = HandoffController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, HandoffControllerTest.SecurityTestConfig.class})
class HandoffControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ReviewService reviewService;

    @MockBean
    private ConsumedMessageMapper consumedMessageMapper;

    @MockBean
    private OutboxEventMapper outboxEventMapper;

    @MockBean
    private ReviewResultMapper reviewResultMapper;

    @MockBean
    private ReviewTaskMapper reviewTaskMapper;

    @MockBean
    private com.acme.review.repository.mapper.ReviewTaskPayloadMapper reviewTaskPayloadMapper;

    @MockBean
    private TaskAuditLogMapper taskAuditLogMapper;

    @MockBean
    private com.acme.review.repository.mapper.FeedbackMapper feedbackMapper;

    @Test
    void shouldGetHandoffWhenFound() throws Exception {
        TaskDetailResponse response = new TaskDetailResponse();
        when(reviewService.getHandoff("task-1")).thenReturn(Optional.of(response));

        mockMvc.perform(get("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isOk());
    }

    @Test
    void shouldReturnNotFoundWhenHandoffMissing() throws Exception {
        when(reviewService.getHandoff("task-404")).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/review/handoff/task-404")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldSubmitHandoff() throws Exception {
        TaskDetailResponse response = new TaskDetailResponse();
        when(reviewService.submitHandoff(eq("task-1"), any())).thenReturn(Optional.of(response));

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validRequest())))
                .andExpect(status().isOk());
    }

    @Test
    void shouldReturnBadRequestWhenDecisionMissing() throws Exception {
        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"operator\":\"alice\",\"comment\":\"ok\"}"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenOperatorBlank() throws Exception {
        HandoffRequest request = validRequest();
        request.setOperator("   ");

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenOperatorTooLong() throws Exception {
        HandoffRequest request = validRequest();
        request.setOperator("a".repeat(256));

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenCommentTooLong() throws Exception {
        HandoffRequest request = validRequest();
        request.setComment("c".repeat(2001));

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnConflictWhenServiceThrowsIllegalStateException() throws Exception {
        when(reviewService.submitHandoff(eq("task-1"), any()))
                .thenThrow(new IllegalStateException("task is not in HUMAN_REVIEW status"));

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validRequest())))
                .andExpect(status().isConflict());
    }

    @Test
    void shouldReturnBadRequestWhenServiceThrowsIllegalArgumentException() throws Exception {
        when(reviewService.submitHandoff(eq("task-1"), any()))
                .thenThrow(new IllegalArgumentException("CHANGES_REQUESTED is not supported for handoff submission"));

        mockMvc.perform(post("/api/review/handoff/task-1")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validRequest())))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnUnauthorizedWhenHeaderMissing() throws Exception {
        mockMvc.perform(get("/api/review/handoff/task-1"))
                .andExpect(status().isUnauthorized());
    }

    private HandoffRequest validRequest() {
        HandoffRequest request = new HandoffRequest();
        request.setDecision(HandoffDecision.APPROVED);
        request.setOperator("alice");
        request.setComment("ok");
        return request;
    }

    @TestConfiguration
    static class SecurityTestConfig {
        @Bean
        SecurityProperties securityProperties() {
            return new SecurityProperties("X-API-Key", "test-key", "callback-token");
        }

        @Bean
        ApiAuthenticationEntryPoint apiAuthenticationEntryPoint() {
            return new ApiAuthenticationEntryPoint();
        }

        @Bean
        ApiKeyAuthenticationFilter apiKeyAuthenticationFilter(SecurityProperties securityProperties) {
            return new ApiKeyAuthenticationFilter(securityProperties);
        }
    }
}
