package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.entity.UserFeedback;
import com.acme.review.service.FeedbackService;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
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

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = FeedbackController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, FeedbackControllerTest.SecurityTestConfig.class})
class FeedbackControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private FeedbackService feedbackService;

    @MockBean
    private com.acme.review.repository.mapper.FeedbackMapper feedbackMapper;

    @MockBean
    private com.acme.review.repository.mapper.ConsumedMessageMapper consumedMessageMapper;

    @MockBean
    private com.acme.review.repository.mapper.OutboxEventMapper outboxEventMapper;

    @MockBean
    private com.acme.review.repository.mapper.ReviewResultMapper reviewResultMapper;

    @MockBean
    private com.acme.review.repository.mapper.ReviewTaskMapper reviewTaskMapper;

    @MockBean
    private com.acme.review.repository.mapper.ReviewTaskPayloadMapper reviewTaskPayloadMapper;

    @MockBean
    private com.acme.review.repository.mapper.TaskAuditLogMapper taskAuditLogMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldSubmitFeedbackAndReturn201() throws Exception {
        Map<String, Object> body = Map.of(
                "taskId", "task-1",
                "sessionId", "session-1",
                "feedbackType", "thumbs_up"
        );

        UserFeedback saved = new UserFeedback();
        saved.setId(1L);
        saved.setTaskId("task-1");
        saved.setSessionId("session-1");
        saved.setFeedbackType("thumbs_up");

        when(feedbackService.submit(any())).thenReturn(saved);

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("accepted"));
    }

    @Test
    void shouldRejectMissingTaskId() throws Exception {
        Map<String, Object> body = Map.of(
                "sessionId", "session-1",
                "feedbackType", "thumbs_up"
        );

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldRejectInvalidFeedbackType() throws Exception {
        Map<String, Object> body = Map.of(
                "taskId", "task-1",
                "sessionId", "session-1",
                "feedbackType", "invalid"
        );

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnStats() throws Exception {
        when(feedbackService.getStats(any(), any(), eq(null)))
                .thenReturn(Map.of("total", 40L, "thumbs_up", 30L, "thumbs_down", 10L, "ratio", "0.75", "daily_breakdown", List.of()));

        mockMvc.perform(get("/api/feedback/stats")
                        .header("X-API-Key", "test-key")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(40))
                .andExpect(jsonPath("$.ratio").value("0.75"));
    }

    @Test
    void shouldExportFeedback() throws Exception {
        UserFeedback fb = new UserFeedback();
        fb.setId(1L);
        fb.setTaskId("task-1");
        fb.setFeedbackType("thumbs_up");
        IPage<UserFeedback> page = new Page<>(1, 10, 1);
        page.setRecords(List.of(fb));

        when(feedbackService.export(any(), any(), eq("review"), eq(1), eq(10)))
                .thenReturn(page);

        mockMvc.perform(get("/api/feedback/export")
                        .header("X-API-Key", "test-key")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z")
                        .param("source", "review")
                        .param("page", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.records[0].taskId").value("task-1"));
    }

    @Test
    void shouldReturnUnauthorizedWhenHeaderMissing() throws Exception {
        mockMvc.perform(get("/api/feedback/stats")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z"))
                .andExpect(status().isUnauthorized());
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
