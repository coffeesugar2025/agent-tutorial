package com.example.ecom.security;

import org.springframework.http.HttpStatus;

/** 统一 API 异常，映射为 {detail: string}。 */
public class ApiException extends RuntimeException {

    private final HttpStatus status;

    public ApiException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public HttpStatus status() { return status; }
    public int statusCode() { return status.value(); }
}
