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
public class BusinessRiskPreparedMethod {

    @JsonProperty("method_id")
    private String methodId;

    private String signature;

    private List<String> annotations = new ArrayList<>();

    @JsonProperty("line_map")
    private BusinessRiskLineMap lineMap;

    @JsonProperty("key_calls")
    private List<String> keyCalls = new ArrayList<>();

    @JsonProperty("transaction_boundary")
    private String transactionBoundary;

    @JsonProperty("lock_semantics")
    private List<String> lockSemantics = new ArrayList<>();

    private String snippet;
}
