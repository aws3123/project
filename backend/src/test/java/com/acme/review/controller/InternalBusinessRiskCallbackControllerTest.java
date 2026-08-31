package com.acme.review.controller;

import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.BusinessRiskCallbackRequest;
import com.acme.review.service.BusinessRiskTaskService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.server.ResponseStatusException;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InternalBusinessRiskCallbackControllerTest {

    private BusinessRiskTaskService taskService;
    private ObjectMapper objectMapper;
    private InternalBusinessRiskCallbackController controller;

    @BeforeEach
    void setUp() throws Exception {
        taskService = mock(BusinessRiskTaskService.class);
        objectMapper = new ObjectMapper();
        SecurityProperties securityProperties = new SecurityProperties("X-API-Key", "test-key", "callback-token");
        controller = new InternalBusinessRiskCallbackController(taskService, securityProperties, objectMapper);

        setField(controller, "callbackTokenHeader", "X-Callback-Token");
        setField(controller, "callbackSignatureHeader", "X-Callback-Signature");
        setField(controller, "callbackTimestampHeader", "X-Callback-Timestamp");
        setField(controller, "callbackNonceHeader", "X-Callback-Nonce");
        setField(controller, "callbackMaxSkewSeconds", 300L);
        setField(controller, "callbackNonceTtlSeconds", 600L);
    }

    @Test
    void shouldAcceptValidCallback() throws Exception {
        String body = objectMapper.writeValueAsString(validPayload());
        String timestamp = String.valueOf(Instant.now().getEpochSecond());
        String nonce = "nonce-valid";
        String signature = sign("callback-token", timestamp, nonce, body);

        HttpServletRequest request = mockRequest(Map.of(
                "X-Callback-Token", "callback-token",
                "X-Callback-Timestamp", timestamp,
                "X-Callback-Nonce", nonce,
                "X-Callback-Signature", signature
        ));

        ResponseEntity<Void> response = controller.callback(body, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        ArgumentCaptor<BusinessRiskCallbackRequest> captor = ArgumentCaptor.forClass(BusinessRiskCallbackRequest.class);
        verify(taskService).handleCallback(captor.capture());
        assertThat(captor.getValue().getTaskId()).isEqualTo("task-1");
    }

    @Test
    void shouldRejectReplayNonce() throws Exception {
        String body = objectMapper.writeValueAsString(validPayload());
        String timestamp = String.valueOf(Instant.now().getEpochSecond());
        String nonce = "nonce-replay";
        String signature = sign("callback-token", timestamp, nonce, body);

        HttpServletRequest request = mockRequest(Map.of(
                "X-Callback-Token", "callback-token",
                "X-Callback-Timestamp", timestamp,
                "X-Callback-Nonce", nonce,
                "X-Callback-Signature", signature
        ));

        controller.callback(body, request);

        assertThatThrownBy(() -> controller.callback(body, request))
                .isInstanceOf(ResponseStatusException.class)
                .extracting(ex -> ((ResponseStatusException) ex).getStatusCode())
                .isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void shouldRejectInvalidSignature() throws Exception {
        String body = objectMapper.writeValueAsString(validPayload());
        String timestamp = String.valueOf(Instant.now().getEpochSecond());

        HttpServletRequest request = mockRequest(Map.of(
                "X-Callback-Token", "callback-token",
                "X-Callback-Timestamp", timestamp,
                "X-Callback-Nonce", "nonce-invalid",
                "X-Callback-Signature", "bad-signature"
        ));

        assertThatThrownBy(() -> controller.callback(body, request))
                .isInstanceOf(ResponseStatusException.class)
                .extracting(ex -> ((ResponseStatusException) ex).getStatusCode())
                .isEqualTo(HttpStatus.UNAUTHORIZED);

        verify(taskService, never()).handleCallback(any());
    }

    @Test
    void shouldRejectExpiredTimestamp() throws Exception {
        String body = objectMapper.writeValueAsString(validPayload());
        String timestamp = String.valueOf(Instant.now().minusSeconds(3600).getEpochSecond());
        String nonce = "nonce-expired";
        String signature = sign("callback-token", timestamp, nonce, body);

        HttpServletRequest request = mockRequest(Map.of(
                "X-Callback-Token", "callback-token",
                "X-Callback-Timestamp", timestamp,
                "X-Callback-Nonce", nonce,
                "X-Callback-Signature", signature
        ));

        assertThatThrownBy(() -> controller.callback(body, request))
                .isInstanceOf(ResponseStatusException.class)
                .extracting(ex -> ((ResponseStatusException) ex).getStatusCode())
                .isEqualTo(HttpStatus.UNAUTHORIZED);

        verify(taskService, never()).handleCallback(any());
    }

    private HttpServletRequest mockRequest(Map<String, String> headers) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader(any())).thenAnswer(invocation -> headers.get(invocation.getArgument(0, String.class)));
        return request;
    }

    private BusinessRiskCallbackRequest validPayload() {
        BusinessRiskCallbackRequest request = new BusinessRiskCallbackRequest();
        request.setTaskId("task-1");
        request.setStatus("completed");
        request.setSuccess(true);
        return request;
    }

    private String sign(String token, String timestamp, String nonce, String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(token.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        String payload = timestamp + "." + nonce + "." + body;
        byte[] digest = mac.doFinal(payload.getBytes(StandardCharsets.UTF_8));
        return HexFormat.of().formatHex(digest);
    }

    private void setField(Object target, String fieldName, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(target, value);
    }
}
