package com.xiaozhan.agent.controller;

import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
public class HealthController {
    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "ok", "backend", "java", "framework", "langchain4j 1.24.0",
                "jdk", System.getProperty("java.version"));
    }
    @GetMapping("/v1/tools")
    public Map<String, Object> tools() {
        return Map.of("tools", java.util.List.of("searchProducts", "getOrder", "calculatePrice"),
                "backend", "java", "read_only", true);
    }
}
