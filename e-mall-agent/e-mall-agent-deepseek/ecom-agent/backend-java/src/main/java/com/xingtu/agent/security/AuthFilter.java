package com.xingtu.agent.security;

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.Ids;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.obs.MetricsCollector;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;
import java.util.Set;

/**
 * 认证过滤器：注入 traceId（X-Trace-Id 透传或自动生成）+ 校验 Bearer JWT。
 * 白名单：POST /api/v1/auth/login、/health、/metrics 与 CORS 预检。
 */
@Component
@Order(1)
public class AuthFilter extends OncePerRequestFilter {

    private static final Set<String> PUBLIC_PATHS = Set.of(
            "/api/v1/auth/login", "/health", "/metrics", "/error", "/favicon.ico");

    private final JwtService jwtService;
    private final MetricsCollector metrics;

    public AuthFilter(JwtService jwtService, MetricsCollector metrics) {
        this.jwtService = jwtService;
        this.metrics = metrics;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String traceId = request.getHeader("X-Trace-Id");
        if (traceId == null || traceId.isBlank()) {
            traceId = Ids.newTraceId();
        }
        TraceContext.setTraceId(traceId);
        MDC.put("traceId", traceId);
        response.setHeader("X-Trace-Id", traceId);
        long start = System.currentTimeMillis();
        int status = 200;
        try {
            if ("OPTIONS".equalsIgnoreCase(request.getMethod()) || isPublic(request.getRequestURI())) {
                filterChain.doFilter(request, response);
                status = response.getStatus();
                return;
            }
            String header = request.getHeader("Authorization");
            if (header == null || !header.startsWith("Bearer ")) {
                status = 401;
                writeError(response, 401, 40100, "未认证：缺少 Authorization: Bearer <jwt>");
                return;
            }
            try {
                jwtService.authenticate(header.substring(7).trim());
            } catch (BizException e) {
                status = e.getHttpStatus();
                writeError(response, e.getHttpStatus(), e.getCode(), e.getMessage());
                return;
            }
            filterChain.doFilter(request, response);
            status = response.getStatus();
        } finally {
            long latency = System.currentTimeMillis() - start;
            metrics.request(request.getRequestURI(), request.getMethod(), status, latency);
            MDC.remove("traceId");
            TraceContext.clear();
        }
    }

    private boolean isPublic(String uri) {
        return PUBLIC_PATHS.contains(uri);
    }

    private void writeError(HttpServletResponse response, int httpStatus, int code, String message)
            throws IOException {
        response.setStatus(httpStatus);
        response.setCharacterEncoding("UTF-8");
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(JsonUtil.toJson(
                new com.xingtu.agent.common.ApiResponse<Void>(code, message, null, TraceContext.traceId())));
    }

    /** 供测试直接构造白名单判断（避免反射）。 */
    public static List<String> publicPaths() {
        return List.copyOf(PUBLIC_PATHS);
    }
}
