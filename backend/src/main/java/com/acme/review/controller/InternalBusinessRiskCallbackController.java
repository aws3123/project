package com.acme.review.controller;

import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.BusinessRiskCallbackRequest;
import com.acme.review.service.BusinessRiskTaskService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@RestController
@RequestMapping("/api/internal/business-risk")
@RequiredArgsConstructor
public class InternalBusinessRiskCallbackController {

    private final BusinessRiskTaskService taskService;
    private final SecurityProperties securityProperties;
    private final ObjectMapper objectMapper;

    private final Map<String, Long> nonceExpiryByValue = new ConcurrentHashMap<>();

    @Value("${business-risk.callback.token-header:X-Callback-Token}")
    private String callbackTokenHeader;

    @Value("${business-risk.callback.signature-header:X-Callback-Signature}")
    private String callbackSignatureHeader;

    @Value("${business-risk.callback.timestamp-header:X-Callback-Timestamp}")
    private String callbackTimestampHeader;

    @Value("${business-risk.callback.nonce-header:X-Callback-Nonce}")
    private String callbackNonceHeader;

    @Value("${business-risk.callback.max-skew-seconds:300}")
    private long callbackMaxSkewSeconds;

    @Value("${business-risk.callback.nonce-ttl-seconds:600}")
    private long callbackNonceTtlSeconds;

    @PostMapping("/callback")
    public ResponseEntity<Void> callback(
            @RequestBody String rawBody,
            HttpServletRequest servletRequest
    ) {
        String callbackToken = servletRequest.getHeader(callbackTokenHeader);
        if (securityProperties.callbackToken() == null || !securityProperties.callbackToken().equals(callbackToken)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid callback token");
        }

        String timestamp = requiredHeader(servletRequest, callbackTimestampHeader);
        String nonce = requiredHeader(servletRequest, callbackNonceHeader);
        String signature = requiredHeader(servletRequest, callbackSignatureHeader);

        long timestampValue;
        try {
            timestampValue = Long.parseLong(timestamp);
        } catch (NumberFormatException ex) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid callback timestamp");
        }

        long now = Instant.now().getEpochSecond();
        if (Math.abs(now - timestampValue) > callbackMaxSkewSeconds) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Expired callback timestamp");
        }

        evictExpiredNonces(now);
        long nonceExpiresAt = now + Math.max(callbackNonceTtlSeconds, callbackMaxSkewSeconds);
        Long existingExpiry = nonceExpiryByValue.putIfAbsent(nonce, nonceExpiresAt);
        if (existingExpiry != null && existingExpiry > now) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Replay callback nonce");
        }
        if (existingExpiry != null && existingExpiry <= now) {
            nonceExpiryByValue.put(nonce, nonceExpiresAt);
        }

        String expectedSignature = sign(callbackToken, timestamp, nonce, rawBody);
        String receivedSignature = signature.startsWith("sha256=") ? signature.substring("sha256=".length()) : signature;
        if (!MessageDigest.isEqual(
                expectedSignature.getBytes(StandardCharsets.UTF_8),
                receivedSignature.getBytes(StandardCharsets.UTF_8)
        )) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid callback signature");
        }

        try {
            BusinessRiskCallbackRequest request = objectMapper.readValue(rawBody, BusinessRiskCallbackRequest.class);
            taskService.handleCallback(request);
            return ResponseEntity.accepted().build();
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid callback payload");
        }
    }

    private String requiredHeader(HttpServletRequest servletRequest, String headerName) {
        String value = servletRequest.getHeader(headerName);
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing callback header: " + headerName);
        }
        return value;
    }

    private void evictExpiredNonces(long nowEpochSeconds) {
        nonceExpiryByValue.entrySet().removeIf(entry -> entry.getValue() <= nowEpochSeconds);
    }

    private String sign(String callbackToken, String timestamp, String nonce, String rawBody) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            SecretKeySpec keySpec = new SecretKeySpec(callbackToken.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
            mac.init(keySpec);
            String signedPayload = timestamp + "." + nonce + "." + rawBody;
            byte[] digest = mac.doFinal(signedPayload.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Failed to verify callback signature");
        }
    }
}
