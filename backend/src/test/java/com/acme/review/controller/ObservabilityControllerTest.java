package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.client.PythonComputeClient;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.service.ReviewService;
import com.acme.review.service.TreeSitterPreprocessService;
import com.acme.review.service.strategy.ReviewStrategyFactory;
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

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = ReviewController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, ObservabilityControllerTest.SecurityTestConfig.class})
class ObservabilityControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ReviewService reviewService;

    @MockBean
    private ReviewStrategyFactory reviewStrategyFactory;

    @MockBean
    private PythonComputeClient pythonComputeClient;

    @MockBean
    private TreeSitterPreprocessService treeSitterPreprocessService;

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

    @Test
    void shouldPropagateTraceIdInErrorResponse() throws Exception {
        ReviewSyncRequest request = new ReviewSyncRequest();
        request.setProjectId("proj-1");
        request.setProjectName("Demo");
        request.setPrUrl("https://example.com/pr/1");
        request.setDiffContent("diff");
        request.setMode(ReviewMode.ASYNC);

        mockMvc.perform(post("/api/review/sync")
                        .header("X-API-Key", "test-key")
                        .header("X-Trace-Id", "trace-test-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(header().string("X-Trace-Id", "trace-test-1"))
                .andExpect(jsonPath("$.traceId").value("trace-test-1"));
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
