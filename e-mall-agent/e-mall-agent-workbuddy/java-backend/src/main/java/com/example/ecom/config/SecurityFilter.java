package com.example.ecom.config;

import com.example.ecom.domain.User;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.security.TokenService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Map;

/**
 * 轻量鉴权过滤器：解析 Bearer HMAC Token，设置当前 User 与 traceId。
 * 只做粗粒度「是否登录」判断，细粒度权限由 RbacGuard 在 service/controller 层执行。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class SecurityFilter extends OncePerRequestFilter {

    private final TokenService tokenService;
    private final RbacGuard rbac;
    private final ObjectMapper mapper;

    public SecurityFilter(TokenService tokenService, RbacGuard rbac, ObjectMapper mapper) {
        this.tokenService = tokenService;
        this.rbac = rbac;
        this.mapper = mapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String path = request.getRequestURI();
        TraceContext.newTrace();
        try {
            User user = resolveUser(request);
            if (user == null) user = new User("anonymous", "访客", "guest");
            TraceContext.setUser(user);

            if (requiresLogin(path) && "guest".equals(RbacGuard.normalize(user.getRole()))) {
                response.setStatus(HttpStatus.UNAUTHORIZED.value());
                response.setContentType("application/json;charset=UTF-8");
                mapper.writeValue(response.getWriter(), Map.of("detail", "需要登录"));
                return;
            }
            chain.doFilter(request, response);
        } finally {
            TraceContext.clear();
        }
    }

    private User resolveUser(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) return null;
        return tokenService.verify(header.substring(7).trim());
    }

    private boolean requiresLogin(String path) {
        if (path.startsWith("/api/auth/login") || path.equals("/api/health")
                || path.equals("/api/infra/health") || path.startsWith("/swagger")
                || path.startsWith("/v3/api-docs") || path.equals("/error")) return false;
        return path.startsWith("/api/chat") || path.startsWith("/api/orders")
                || path.startsWith("/api/workflows") || path.startsWith("/api/frontier")
                || path.startsWith("/api/audit") || path.startsWith("/api/traces")
                || path.startsWith("/api/graphs") || path.startsWith("/api/capabilities");
    }
}
