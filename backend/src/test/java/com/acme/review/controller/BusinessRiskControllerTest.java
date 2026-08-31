package com.acme.review.controller;

import com.acme.review.dto.BusinessRiskSourceMetadataRequest;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.exception.GlobalExceptionHandler;
import com.acme.review.service.BusinessRiskSseService;
import com.acme.review.service.BusinessRiskTaskService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class BusinessRiskControllerTest {

    private MockMvc mockMvc;
    private BusinessRiskTaskService taskService;

    @BeforeEach
    void setUp() {
        taskService = mock(BusinessRiskTaskService.class);
        BusinessRiskSseService sseService = mock(BusinessRiskSseService.class);
        BusinessRiskController controller = new BusinessRiskController(taskService, sseService, new ObjectMapper());
        ReflectionTestUtils.setField(controller, "maxFiles", 50);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void submitReturnsTraceIdAndDeterministicSessionId() throws Exception {
        when(taskService.createTask(any(BusinessRiskSourceMetadataRequest.class))).thenReturn("biz-risk-1");
        when(taskService.resolveSessionId("biz-risk-1")).thenReturn("session-biz-risk-1");
        when(taskService.dispatchToPythonAsync(any(), any(), eq("biz-risk-1"), eq("session-biz-risk-1")))
                .thenReturn(ReviewTaskStatus.PENDING);

        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile(
                                "files",
                                "TicketController.java",
                                "text/x-java-source",
                                "class TicketController {}".getBytes(StandardCharsets.UTF_8)
                        ))
                        .param("metadata", "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}")
                        .header("X-Trace-Id", "trace-header-1"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.taskId").value("biz-risk-1"))
                .andExpect(jsonPath("$.sessionId").value("session-biz-risk-1"))
                .andExpect(jsonPath("$.traceId").value("trace-header-1"));
    }

    @Test
    void submitAcceptsBracketedFilesField() throws Exception {
        when(taskService.createTask(any(BusinessRiskSourceMetadataRequest.class))).thenReturn("biz-risk-2");
        when(taskService.resolveSessionId("biz-risk-2")).thenReturn("session-biz-risk-2");
        when(taskService.dispatchToPythonAsync(any(), any(), eq("biz-risk-2"), eq("session-biz-risk-2")))
                .thenReturn(ReviewTaskStatus.PENDING);

        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile(
                                "files[]",
                                "TicketOrderService.java",
                                "text/x-java-source",
                                "class TicketOrderService {}".getBytes(StandardCharsets.UTF_8)
                        ))
                        .param("metadata", "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}"))
                .andExpect(status().isAccepted());
    }

    @Test
    void submitRejectsNonJavaFiles() throws Exception {
        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile("files", "notes.txt", "text/plain", "hello".getBytes(StandardCharsets.UTF_8)))
                        .param("metadata", "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}")
                        .header("X-Trace-Id", "trace-bad-file-1"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.message").value("only .java files are supported"));
    }
}
