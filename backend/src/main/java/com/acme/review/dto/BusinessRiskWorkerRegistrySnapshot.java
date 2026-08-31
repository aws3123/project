package com.acme.review.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskWorkerRegistrySnapshot {

    private int activeWorkers;
    private int readyWorkers;
    private int staleWorkers;
    private int versionMatchedWorkers;
    private int availableSlots;
    private boolean dispatchAllowed;
    private String blockReason;
}
