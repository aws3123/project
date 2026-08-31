package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskAnalysisHints {

    @JsonProperty("candidate_risk_types")
    private List<String> candidateRiskTypes = new ArrayList<>();

    @JsonProperty("focus_methods")
    private List<String> focusMethods = new ArrayList<>();

    @JsonProperty("focus_call_paths")
    private List<String> focusCallPaths = new ArrayList<>();

    @JsonProperty("hotspot_method_ids")
    private List<String> hotspotMethodIds = new ArrayList<>();
}
