package com.acme.review.exception;

public class PythonHttpException extends PythonServiceException {

    private final int statusCode;
    private final boolean retryable;

    public PythonHttpException(String message, int statusCode, boolean retryable) {
        super(message);
        this.statusCode = statusCode;
        this.retryable = retryable;
    }

    public int getStatusCode() {
        return statusCode;
    }

    public boolean isRetryable() {
        return retryable;
    }
}
