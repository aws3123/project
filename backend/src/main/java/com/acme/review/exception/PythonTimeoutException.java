package com.acme.review.exception;

public class PythonTimeoutException extends RuntimeException {

    public PythonTimeoutException(String message, Throwable cause) {
        super(message, cause);
    }
}
