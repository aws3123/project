package com.acme.review.exception;

import lombok.Getter;

@Getter
public class BusinessRiskPreprocessException extends RuntimeException {

    private final String errorCode;

    public BusinessRiskPreprocessException(String errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public BusinessRiskPreprocessException(String errorCode, String message, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
    }
}
