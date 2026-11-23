package com.example.ecom.controller;

import com.example.ecom.domain.User;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.service.AuthService;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final RbacGuard rbac;

    public AuthController(AuthService authService, RbacGuard rbac) {
        this.authService = authService;
        this.rbac = rbac;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record LoginRequest(String username, String password) {}

    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody LoginRequest request) {
        return authService.login(request.username(), request.password());
    }

    @GetMapping("/me")
    public Map<String, Object> me() {
        User user = TraceContext.user();
        if (user == null) return Map.of("id", "anonymous", "name", "访客", "role", "guest",
                "permissions", rbac.permissionsFor("guest"));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", user.getId());
        result.put("name", user.getName());
        result.put("role", user.getRole());
        result.put("permissions", rbac.permissionsFor(user.getRole()));
        return result;
    }
}
