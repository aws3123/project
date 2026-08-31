package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Min;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskLineMap {

    @Min(1)
    @JsonProperty("start_line")
    private int startLine;

    @Min(1)
    @JsonProperty("end_line")
    private int endLine;
}
