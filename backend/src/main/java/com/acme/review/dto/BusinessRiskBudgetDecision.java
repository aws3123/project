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
public class BusinessRiskBudgetDecision {

    private String decision;

    @JsonProperty("raw_total_bytes")
    private long rawTotalBytes;

    @JsonProperty("prepared_total_bytes")
    private long preparedTotalBytes;

    @JsonProperty("dropped_files")
    private List<String> droppedFiles = new ArrayList<>();

    @JsonProperty("dropped_methods")
    private List<String> droppedMethods = new ArrayList<>();

    @JsonProperty("dropped_hotspots")
    private List<String> droppedHotspots = new ArrayList<>();
}
