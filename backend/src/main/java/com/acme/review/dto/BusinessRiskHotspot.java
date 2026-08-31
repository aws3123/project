package com.acme.review.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskHotspot {

    @NotBlank
    private String methodId;

    @NotBlank
    private String rawSnippet;

    @NotBlank
    private String reason;

    @Valid
    private BusinessRiskLineMap lineMap;
}
