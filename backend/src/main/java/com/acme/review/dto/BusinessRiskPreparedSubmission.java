package com.acme.review.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskPreparedSubmission {

    private BusinessRiskSourcePackage sourcePackage;
    private BusinessRiskAnalysisHints analysisHints;
    private long rawTotalBytes;
    private long preparedTotalBytes;
}
