package com.acme.review.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class ReviewDispatchRequest {

    @NotBlank
    private String projectId;

    @NotBlank
    private String projectName;

    @NotBlank
    private String prUrl;

    @NotBlank
    @Size(max = 200000)
    private String diffContent;

    @NotBlank
    @Size(max = 2000)
    private String question;
}
