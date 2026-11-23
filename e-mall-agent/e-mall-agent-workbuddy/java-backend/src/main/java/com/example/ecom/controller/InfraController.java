package com.example.ecom.controller;

import com.example.ecom.service.InfraHealthService;
import com.example.ecom.service.WorkflowService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class InfraController {

    private final InfraHealthService health;
    private final WorkflowService workflow;
    private final String appName;

    public InfraController(InfraHealthService health, WorkflowService workflow,
                           @Value("${APP_NAME:ecom-java-backend}") String appName) {
        this.health = health;
        this.workflow = workflow;
        this.appName = appName;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "ok", "service", appName, "provider", "java");
    }

    @GetMapping("/infra/health")
    public Map<String, Object> infraHealth() {
        return health.health();
    }

    @GetMapping("/infra/events")
    public List<String> events() {
        return workflow.drainEvents();
    }
}
