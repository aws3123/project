package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.TaskDetailResponse;
import com.acme.review.dto.TaskListResponse;
import com.acme.review.repository.mapper.ConsumedMessageMapper;
import com.acme.review.repository.mapper.OutboxEventMapper;
import com.acme.review.repository.mapper.ReviewResultMapper;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import com.acme.review.repository.mapper.TaskAuditLogMapper;
import com.acme.review.service.ReviewService;
import com.acme.review.service.strategy.AsyncStrategy;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = TaskController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, TaskControllerTest.SecurityTestConfig.class})
class TaskControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private ReviewService reviewService;

    @MockBean
    private AsyncStrategy asyncStrategy;

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
    void shouldReturnTaskDetailWhenFound() throws Exception {
        TaskDetailResponse response = new TaskDetailResponse();
        TaskDetailResponse.TaskInfo task = new TaskDetailResponse.TaskInfo();
        task.setTaskId("task-1");
        task.setStatus("SUCCESS");
        response.setTask(task);

        when(reviewService.getTaskDetail("task-1")).thenReturn(Optional.of(response));

        mockMvc.perform(get("/api/review/tasks/task-1")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.task.taskId").value("task-1"))
                .andExpect(jsonPath("$.task.status").value("SUCCESS"));
    }

    @Test
    void shouldReturnNotFoundWhenTaskMissing() throws Exception {
        when(reviewService.getTaskDetail("missing")).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/review/tasks/missing")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturnBadRequestWhenPageIsZero() throws Exception {
        mockMvc.perform(get("/api/review/tasks")
                        .param("page", "0")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenSizeIsZero() throws Exception {
        mockMvc.perform(get("/api/review/tasks")
                        .param("size", "0")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenSizeExceedsMax() throws Exception {
        mockMvc.perform(get("/api/review/tasks")
                        .param("size", "101")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(reviewService);
    }

    @Test
    void shouldReturnBadRequestWhenStatusIsUnknown() throws Exception {
        when(reviewService.listTasks(1, 5, null, "unknown"))
                .thenThrow(new IllegalArgumentException("Unknown ReviewTaskStatus value: unknown"));

        mockMvc.perform(get("/api/review/tasks")
                        .param("status", "unknown")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnTaskListForValidRequest() throws Exception {
        TaskDetailResponse.TaskInfo item = new TaskDetailResponse.TaskInfo();
        item.setTaskId("task-1");
        item.setProjectId("proj-1");
        item.setStatus("SUCCESS");
        item.setMode("SYNC");

        TaskListResponse response = TaskListResponse.of(List.of(item), 4, 2, 3);
        when(reviewService.listTasks(2, 3, "proj-1", "success")).thenReturn(response);

        mockMvc.perform(get("/api/review/tasks")
                        .param("page", "2")
                        .param("size", "3")
                        .param("projectId", "proj-1")
                        .param("status", "success")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].taskId").value("task-1"))
                .andExpect(jsonPath("$.items[0].projectId").value("proj-1"))
                .andExpect(jsonPath("$.items[0].status").value("SUCCESS"))
                .andExpect(jsonPath("$.items[0].mode").value("SYNC"))
                .andExpect(jsonPath("$.total").value(4))
                .andExpect(jsonPath("$.page").value(2))
                .andExpect(jsonPath("$.size").value(3))
                .andExpect(jsonPath("$.totalPages").value(2));
    }

    @Test
    void shouldRetryTask() throws Exception {
        doNothing().when(asyncStrategy).retryStuckTask("task-1");

        mockMvc.perform(post("/api/review/tasks/task-1/retry")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.taskId").value("task-1"))
                .andExpect(jsonPath("$.status").value("RETRYING"));
    }

    @Test
    void shouldReturnNotFoundWhenRetryTaskMissing() throws Exception {
        doThrow(new IllegalArgumentException("Task not found: missing"))
                .when(asyncStrategy).retryStuckTask("missing");

        mockMvc.perform(post("/api/review/tasks/missing/retry")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldReturnConflictWhenRetryTaskStateIsInvalid() throws Exception {
        doThrow(new IllegalStateException("Only FAILED tasks can be retried, current: SUCCESS"))
                .when(asyncStrategy).retryStuckTask("task-2");

        mockMvc.perform(post("/api/review/tasks/task-2/retry")
                        .header("X-API-Key", "test-key"))
                .andExpect(status().isConflict());
    }

    @Test
    void shouldReturnUnauthorizedWhenHeaderMissing() throws Exception {
        mockMvc.perform(get("/api/review/tasks/task-1"))
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
