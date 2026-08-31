package com.acme.review.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class HandoffRequest {
    @NotNull
    private HandoffDecision decision;

    @NotBlank
    @Size(max = 255)
    private String operator;

    @Size(max = 2000)
    private String comment;
}
