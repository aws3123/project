package com.acme.review.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskMethodSkeleton {

    @NotBlank
    private String methodId;

    @NotBlank
    private String signature;

    private List<String> controlFlowSummary = new ArrayList<>();

    private List<String> keyCalls = new ArrayList<>();

    @Valid
    private BusinessRiskLineMap lineMap;
}
