package com.acme.review.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskSourceBundle {

    @Min(0)
    private int fileCount;

    @Valid
    private List<BusinessRiskSourceFile> files = new ArrayList<>();
}
