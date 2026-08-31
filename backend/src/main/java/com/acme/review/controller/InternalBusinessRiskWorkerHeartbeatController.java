package com.acme.review.controller;

import com.acme.review.dto.BusinessRiskWorkerHeartbeatRequest;
import com.acme.review.service.BusinessRiskWorkerRegistryService;
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

@RestController
@RequestMapping("/api/internal/business-risk")
@RequiredArgsConstructor
public class InternalBusinessRiskWorkerHeartbeatController {

    private final BusinessRiskWorkerRegistryService workerRegistryService;

    @Value("${business-risk.worker.token-header:X-Worker-Token}")
    private String workerTokenHeader;

    @Value("${security.callback-token:dev-callback}")
    private String workerToken;

    @PostMapping("/worker-heartbeat")
    public ResponseEntity<Void> heartbeat(
            @RequestBody BusinessRiskWorkerHeartbeatRequest request,
            HttpServletRequest servletRequest
    ) {
        String providedToken = servletRequest.getHeader(workerTokenHeader);
        if (providedToken == null || providedToken.isBlank()) {
            providedToken = servletRequest.getHeader("X-Callback-Token");
        }
        if (workerToken == null || workerToken.isBlank() || !workerToken.equals(providedToken)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid worker heartbeat token");
        }

        workerRegistryService.upsert(request);
        return ResponseEntity.accepted().build();
    }
}
