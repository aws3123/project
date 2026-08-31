package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskPreparedCallEdge {

    private String from;

    private String to;

    @JsonProperty("edge_type")
    private String edgeType;
}
