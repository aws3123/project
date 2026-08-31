package com.acme.review.exception;

import lombok.Getter;

@Getter
public class BusinessRiskDispatchGateException extends RuntimeException {

    private final String errorCode;

    public BusinessRiskDispatchGateException(String errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }
}
