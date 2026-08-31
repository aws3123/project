package com.acme.review.exception;

import lombok.Getter;

@Getter
public class AsyncDispatchException extends RuntimeException {

    private final String taskId;

    public AsyncDispatchException(String taskId, String message) {
        super(message);
        this.taskId = taskId;
    }

    public AsyncDispatchException(String taskId, String message, Throwable cause) {
        super(message, cause);
        this.taskId = taskId;
    }
}
