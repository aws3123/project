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
public class BusinessRiskSourcePackage {

    @JsonProperty("file_count")
    private int fileCount;

    private List<BusinessRiskPreparedSourceFile> files = new ArrayList<>();

    @JsonProperty("call_graph")
    private List<BusinessRiskPreparedCallEdge> callGraph = new ArrayList<>();

    private BusinessRiskBudgetDecision budget;

    @JsonProperty("preprocess_findings")
    private List<String> preprocessFindings = new ArrayList<>();
}
