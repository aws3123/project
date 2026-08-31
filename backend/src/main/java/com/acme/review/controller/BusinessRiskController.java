package com.acme.review.controller;

import com.acme.review.dto.BusinessRiskSourceMetadataRequest;
import com.acme.review.dto.BusinessRiskSourceSubmitResponse;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.service.BusinessRiskSseService;
import com.acme.review.service.BusinessRiskTaskService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.multipart.MultipartHttpServletRequest;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

@RestController
@RequestMapping("/api/business-risk")
@RequiredArgsConstructor
public class BusinessRiskController {

    private final BusinessRiskTaskService taskService;
    private final BusinessRiskSseService sseService;
    private final ObjectMapper objectMapper;

    @Value("${business-risk.source.max-files:50}")
    private int maxFiles;

    @PostMapping(value = "/source", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BusinessRiskSourceSubmitResponse> submit(
            MultipartHttpServletRequest multipartRequest,
            @RequestHeader(value = "X-Trace-Id", required = false) String traceIdHeader
    ) {
        BusinessRiskSourceMetadataRequest metadata = resolveMetadata(multipartRequest);
        validateMetadata(metadata);
        List<MultipartFile> files = resolveFiles(multipartRequest);
        validateFiles(files);

        String traceId = (metadata.getTraceId() != null && !metadata.getTraceId().isBlank())
                ? metadata.getTraceId()
                : (traceIdHeader != null && !traceIdHeader.isBlank() ? traceIdHeader : UUID.randomUUID().toString());
        metadata.setTraceId(traceId);

        String taskId = taskService.createTask(metadata);
        String sessionId = taskService.resolveSessionId(taskId);
        sseService.publish(sessionId, taskId, "task_created", "{\"status\":\"PENDING\",\"traceId\":\"" + traceId + "\"}");
        ReviewTaskStatus status = taskService.dispatchToPythonAsync(metadata, files, taskId, sessionId);

        return ResponseEntity.accepted().body(new BusinessRiskSourceSubmitResponse(
                taskId,
                status.name(),
                "/api/business-risk/stream",
                sessionId,
                traceId
        ));
    }

    private BusinessRiskSourceMetadataRequest resolveMetadata(MultipartHttpServletRequest multipartRequest) {
        String metadataJson = multipartRequest.getParameter("metadata");
        if ((metadataJson == null || metadataJson.isBlank()) && multipartRequest.getFile("metadata") != null) {
            try {
                metadataJson = new String(multipartRequest.getFile("metadata").getBytes());
            } catch (Exception ex) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "metadata is invalid");
            }
        }
        if (metadataJson == null || metadataJson.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "metadata is required");
        }
        try {
            return objectMapper.readValue(metadataJson, BusinessRiskSourceMetadataRequest.class);
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "metadata is invalid");
        }
    }

    private List<MultipartFile> resolveFiles(MultipartHttpServletRequest multipartRequest) {
        List<MultipartFile> resolved = new ArrayList<>();
        resolved.addAll(multipartRequest.getFiles("files"));
        resolved.addAll(multipartRequest.getFiles("files[]"));
        return resolved;
    }

    private void validateMetadata(BusinessRiskSourceMetadataRequest metadata) {
        if (metadata.getSchemaVersion() == null || metadata.getSchemaVersion().isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "schemaVersion is required");
        }
        if (metadata.getProjectId() == null || metadata.getProjectId().isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "projectId is required");
        }
        if (metadata.getRepo() == null || metadata.getRepo().isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "repo is required");
        }
        if (metadata.getBranch() == null || metadata.getBranch().isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "branch is required");
        }
    }

    private void validateFiles(List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "files is required");
        }
        if (files.size() > maxFiles) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "files exceeds max " + maxFiles);
        }
        for (MultipartFile file : files) {
            String originalFilename = file.getOriginalFilename();
            if (originalFilename == null || !originalFilename.toLowerCase(Locale.ROOT).endsWith(".java")) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "only .java files are supported");
            }
        }
    }
}
