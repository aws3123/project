package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.DispatchRoute;
import com.acme.review.dto.ReviewAsyncResponse;
import com.acme.review.dto.ReviewDispatchRequest;
import com.acme.review.dto.ReviewDispatchResponse;
import com.acme.review.dto.ReviewMode;
import com.acme.review.dto.ReviewSyncRequest;
import com.acme.review.dto.ReviewSyncResponse;
import com.acme.review.exception.AsyncDispatchException;
import com.acme.review.service.ReviewDispatchDecision;
import com.acme.review.client.PythonComputeClient;
import com.acme.review.service.TreeSitterPreprocessService;
import com.acme.review.service.strategy.AsyncStrategy;
import com.acme.review.service.strategy.DispatchStrategy;
import com.acme.review.service.strategy.ReviewStrategyFactory;
import com.acme.review.service.strategy.SyncStrategy;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = ReviewController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, ReviewControllerTest.SecurityTestConfig.class})
class ReviewControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ReviewStrategyFactory reviewStrategyFactory;

    @MockBean
    private SyncStrategy syncStrategy;

    @MockBean
    private AsyncStrategy asyncStrategy;

    @MockBean
    private DispatchStrategy dispatchStrategy;

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

    @MockBean
    private PythonComputeClient pythonComputeClient;

    @MockBean
    private TreeSitterPreprocessService treeSitterPreprocessService;

    private ReviewSyncRequest request;

    @BeforeEach
    void setUp() {
        request = new ReviewSyncRequest();
        request.setProjectId("proj-1");
        request.setProjectName("Demo");
        request.setPrUrl("https://example.com/pr/1");
        request.setDiffContent("diff");
        request.setMode(ReviewMode.SYNC);

        Mockito.when(reviewStrategyFactory.getSyncStrategy()).thenReturn(syncStrategy);
        Mockito.when(reviewStrategyFactory.getAsyncStrategy()).thenReturn(asyncStrategy);
        Mockito.when(reviewStrategyFactory.getDispatchStrategy()).thenReturn(dispatchStrategy);
    }

    @Test
    void shouldReturnOkWhenServiceSucceeds() throws Exception {
        Mockito.when(syncStrategy.executeSync(any())).thenReturn(
                new ReviewSyncResponse("task-1", 0.8, "ok", false, List.of("detail"))
        );

        mockMvc.perform(post("/api/review/sync")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                )
                .andExpect(status().isOk());
    }

    @Test
    void shouldReturnAcceptedWhenAsyncSucceeds() throws Exception {
        request.setMode(ReviewMode.ASYNC);
        Mockito.when(asyncStrategy.publishAsync(any())).thenReturn(new ReviewAsyncResponse("task-2", "QUEUED"));

        mockMvc.perform(post("/api/review/async")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                )
                .andExpect(status().isAccepted());
    }

    @Test
    void shouldKeepAsyncPublicContractStable() throws Exception {
        request.setMode(ReviewMode.ASYNC);
        Mockito.when(asyncStrategy.publishAsync(any())).thenReturn(new ReviewAsyncResponse("task-2", "QUEUED"));

        mockMvc.perform(post("/api/review/async")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.taskId").value("task-2"))
                .andExpect(jsonPath("$.status").value("QUEUED"));
    }

    @Test
    void shouldReturnServiceUnavailableWhenAsyncDispatchFails() throws Exception {
        request.setMode(ReviewMode.ASYNC);
        Mockito.when(asyncStrategy.publishAsync(any()))
                .thenThrow(new AsyncDispatchException("task-err-1", "Failed to publish, taskId=task-err-1"));

        mockMvc.perform(post("/api/review/async")
                        .header("X-API-Key", "test-key")
                        .header("X-Trace-Id", "trace-test-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value("MessageQueueUnavailable"))
                .andExpect(jsonPath("$.message").value(containsString("taskId=task-err-1")))
                .andExpect(jsonPath("$.traceId").value("trace-test-1"));
    }

    @Test
    void shouldReturnOkWhenDispatchRoutesToSync() throws Exception {
        ReviewDispatchRequest dispatchRequest = new ReviewDispatchRequest();
        dispatchRequest.setProjectId("proj-1");
        dispatchRequest.setProjectName("Demo");
        dispatchRequest.setPrUrl("https://example.com/pr/1");
        dispatchRequest.setDiffContent("diff --git a/frontend/src/App.tsx b/frontend/src/App.tsx");
        dispatchRequest.setQuestion("帮我快速判断这个改动有没有明显风险");

        ReviewSyncResponse syncResponse = new ReviewSyncResponse("task-dispatch-sync", 0.3, "summary", false, List.of("detail"));
        Mockito.when(dispatchStrategy.dispatch(any())).thenReturn(
                ReviewDispatchResponse.fromSync(
                        new ReviewDispatchDecision(DispatchRoute.SYNC, "direct_sync_small_simple", 1.0, false),
                        syncResponse
                )
        );

        mockMvc.perform(post("/api/review/dispatch")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(dispatchRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.route").value("SYNC"))
                .andExpect(jsonPath("$.taskId").value("task-dispatch-sync"))
                .andExpect(jsonPath("$.dispatchReason").value("direct_sync_small_simple"))
                .andExpect(jsonPath("$.result.riskSummary").value("summary"));
    }

    @Test
    void shouldReturnUnauthorizedWhenDispatchHeaderMissing() throws Exception {
        ReviewDispatchRequest dispatchRequest = new ReviewDispatchRequest();
        dispatchRequest.setProjectId("proj-1");
        dispatchRequest.setProjectName("Demo");
        dispatchRequest.setPrUrl("https://example.com/pr/1");
        dispatchRequest.setDiffContent("diff");
        dispatchRequest.setQuestion("帮我快速判断这个改动有没有明显风险");

        mockMvc.perform(post("/api/review/dispatch")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(dispatchRequest)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldReturnUnauthorizedWhenHeaderMissing() throws Exception {
        mockMvc.perform(post("/api/review/sync")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                )
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldReturnBadRequestWhenModeNotSync() throws Exception {
        request.setMode(ReviewMode.ASYNC);
        mockMvc.perform(post("/api/review/sync")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                )
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnBadRequestWhenModeNotAsync() throws Exception {
        request.setMode(ReviewMode.SYNC);
        mockMvc.perform(post("/api/review/async")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                )
                .andExpect(status().isBadRequest());
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
