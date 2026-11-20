package com.example.order.common;

import com.example.order.idem.IdempotencyGuard;
import com.example.order.service.OrderService;
import com.example.order.state.OrderStateMachine;
import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(IdempotencyGuard.IdempotentInProgressException.class)
    public ResponseEntity<Map<String, Object>> inProgress(IdempotencyGuard.IdempotentInProgressException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header(HttpHeaders.RETRY_AFTER, "1")
                .body(body("IDEMPOTENT_IN_PROGRESS", e.getMessage()));
    }

    @ExceptionHandler(OrderService.InsufficientStockException.class)
    public ResponseEntity<Map<String, Object>> soldOut(OrderService.InsufficientStockException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(body("SOLD_OUT", e.getMessage()));
    }

    @ExceptionHandler(OrderService.OrderConcurrentException.class)
    public ResponseEntity<Map<String, Object>> concurrent(OrderService.OrderConcurrentException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(body("CONCURRENT_MODIFICATION", e.getMessage()));
    }

    @ExceptionHandler(OrderStateMachine.IllegalStateTransitionException.class)
    public ResponseEntity<Map<String, Object>> illegalTransition(OrderStateMachine.IllegalStateTransitionException e) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(body("ILLEGAL_TRANSITION", e.getMessage()));
    }

    @ExceptionHandler({IllegalArgumentException.class,
                       MethodArgumentNotValidException.class,
                       ConstraintViolationException.class})
    public ResponseEntity<Map<String, Object>> badRequest(Exception e) {
        return ResponseEntity.badRequest().body(body("BAD_REQUEST", e.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> internal(Exception e) {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(body("INTERNAL_ERROR", "internal error"));
    }

    private Map<String, Object> body(String code, String message) {
        return Map.of("code", code, "message", message == null ? "" : message);
    }
}
