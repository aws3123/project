package com.acme.review.exception;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import org.springframework.beans.TypeMismatchException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.method.ParameterValidationResult;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.stream.Collectors;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final String TRACE_ID_ATTR = "traceId";

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiError> handleValidationException(MethodArgumentNotValidException ex, HttpServletRequest request) {
        String message = ex.getBindingResult().getFieldErrors().stream()
                .map(error -> formatValidationError(error.getField(), error.getDefaultMessage()))
                .collect(Collectors.joining(", "));
        ApiError error = new ApiError(Instant.now(), HttpStatus.BAD_REQUEST.value(), "ValidationError", message, request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.badRequest().body(error);
    }

    @ExceptionHandler(HandlerMethodValidationException.class)
    public ResponseEntity<ApiError> handleHandlerMethodValidationException(HandlerMethodValidationException ex, HttpServletRequest request) {
        String message = ex.getAllValidationResults().stream()
                .flatMap(result -> result.getResolvableErrors().stream()
                        .map(validationError -> formatValidationError(resolveParameterName(result), validationError.getDefaultMessage())))
                .collect(Collectors.joining(", "));
        ApiError error = new ApiError(
                Instant.now(),
                HttpStatus.BAD_REQUEST.value(),
                "ValidationError",
                message.isBlank() ? "Validation failed" : message,
                request.getRequestURI(),
                extractTraceId(request)
        );
        return ResponseEntity.badRequest().body(error);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiError> handleMethodArgumentTypeMismatchException(MethodArgumentTypeMismatchException ex, HttpServletRequest request) {
        return ResponseEntity.badRequest().body(buildTypeMismatchError(ex, request));
    }

    @ExceptionHandler(TypeMismatchException.class)
    public ResponseEntity<ApiError> handleTypeMismatchException(TypeMismatchException ex, HttpServletRequest request) {
        return ResponseEntity.badRequest().body(buildTypeMismatchError(ex, request));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiError> handleConstraintViolationException(ConstraintViolationException ex, HttpServletRequest request) {
        String message = ex.getConstraintViolations().stream()
                .map(violation -> formatValidationError(violation.getPropertyPath().toString(), violation.getMessage()))
                .collect(Collectors.joining(", "));
        ApiError error = new ApiError(
                Instant.now(),
                HttpStatus.BAD_REQUEST.value(),
                "ValidationError",
                message.isBlank() ? "Validation failed" : message,
                request.getRequestURI(),
                extractTraceId(request)
        );
        return ResponseEntity.badRequest().body(error);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiError> handleIllegalArgument(IllegalArgumentException ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.BAD_REQUEST.value(), "BadRequest", ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.badRequest().body(error);
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<ApiError> handleIllegalState(IllegalStateException ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.CONFLICT.value(), "Conflict", ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.status(HttpStatus.CONFLICT).body(error);
    }

    @ExceptionHandler(PythonServiceException.class)
    public ResponseEntity<ApiError> handlePythonException(PythonServiceException ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.BAD_GATEWAY.value(), "PythonServiceError", ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error);
    }

    @ExceptionHandler(BusinessRiskPreprocessException.class)
    public ResponseEntity<ApiError> handleBusinessRiskPreprocessException(BusinessRiskPreprocessException ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.UNPROCESSABLE_ENTITY.value(), ex.getErrorCode(), ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(error);
    }

    @ExceptionHandler(BusinessRiskDispatchGateException.class)
    public ResponseEntity<ApiError> handleBusinessRiskDispatchGateException(BusinessRiskDispatchGateException ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.SERVICE_UNAVAILABLE.value(), ex.getErrorCode(), ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(error);
    }

    @ExceptionHandler(AsyncDispatchException.class)
    public ResponseEntity<ApiError> handleAsyncDispatchException(AsyncDispatchException ex, HttpServletRequest request) {
        ApiError error = new ApiError(
                Instant.now(),
                HttpStatus.SERVICE_UNAVAILABLE.value(),
                "MessageQueueUnavailable",
                ex.getMessage(),
                request.getRequestURI(),
                extractTraceId(request)
        );
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(error);
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ApiError> handleResponseStatusException(ResponseStatusException ex, HttpServletRequest request) {
        HttpStatus status = HttpStatus.valueOf(ex.getStatusCode().value());
        ApiError error = new ApiError(
                Instant.now(),
                status.value(),
                status.getReasonPhrase(),
                ex.getReason(),
                request.getRequestURI(),
                extractTraceId(request)
        );
        return ResponseEntity.status(status).body(error);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleGenericException(Exception ex, HttpServletRequest request) {
        ApiError error = new ApiError(Instant.now(), HttpStatus.INTERNAL_SERVER_ERROR.value(), "InternalError", ex.getMessage(), request.getRequestURI(), extractTraceId(request));
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(error);
    }

    private String resolveParameterName(ParameterValidationResult result) {
        String parameterName = result.getMethodParameter().getParameterName();
        return parameterName != null && !parameterName.isBlank() ? parameterName : "request";
    }

    private ApiError buildTypeMismatchError(TypeMismatchException ex, HttpServletRequest request) {
        String target = resolveTypeMismatchTarget(ex);
        String value = ex.getValue() != null ? String.valueOf(ex.getValue()) : "null";
        String message = formatValidationError(target, "Invalid value '" + value + "'");
        return new ApiError(
                Instant.now(),
                HttpStatus.BAD_REQUEST.value(),
                "ValidationError",
                message,
                request.getRequestURI(),
                extractTraceId(request)
        );
    }

    private String resolveTypeMismatchTarget(TypeMismatchException ex) {
        if (ex instanceof MethodArgumentTypeMismatchException methodArgumentTypeMismatchException) {
            String parameterName = methodArgumentTypeMismatchException.getName();
            if (parameterName != null && !parameterName.isBlank()) {
                return parameterName;
            }
        }
        String propertyName = ex.getPropertyName();
        return propertyName != null && !propertyName.isBlank() ? propertyName : "request";
    }

    private String formatValidationError(String field, String message) {
        String target = field != null && !field.isBlank() ? field : "request";
        String detail = message != null && !message.isBlank() ? message : "Validation failed";
        return target + ":" + detail;
    }

    private String extractTraceId(HttpServletRequest request) {
        Object traceId = request.getAttribute(TRACE_ID_ATTR);
        return traceId != null ? String.valueOf(traceId) : null;
    }
}
