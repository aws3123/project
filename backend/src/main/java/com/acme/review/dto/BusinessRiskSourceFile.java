package com.acme.review.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskSourceFile {

    @NotBlank
    private String path;

    @Pattern(regexp = "java", message = "language must be java")
    private String language;

    private String classSummary;

    @Valid
    private List<BusinessRiskMethodSkeleton> methodSkeletons = new ArrayList<>();

    @Valid
    private List<BusinessRiskHotspot> hotspots = new ArrayList<>();
}
