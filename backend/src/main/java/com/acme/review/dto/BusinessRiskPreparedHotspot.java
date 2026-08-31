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
public class BusinessRiskPreparedHotspot {

    @JsonProperty("method_id")
    private String methodId;

    private String reason;

    @JsonProperty("risk_tags")
    private List<String> riskTags = new ArrayList<>();

    @JsonProperty("line_map")
    private BusinessRiskLineMap lineMap;

    private String snippet;
}
