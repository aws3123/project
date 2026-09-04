package com.acme.review.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
public class ReviewSyncRequest {

    @NotBlank
    private String projectId;

    @NotBlank
    private String projectName;

    @NotBlank
    private String prUrl;

    @NotBlank
    @Size(max = 200000)
    private String diffContent;

    @NotNull
    private ReviewMode mode;

    private String taskId;

    private String sessionId;

    private String question;

    private List<Map<String, Object>> entities;

    private List<Map<String, Object>> relations;
}
