package com.xingtu.agent.security;

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.TraceContext;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.List;

/**
 * 管理端 RBAC：/api/v1/admin/** 需要 ADMIN，/api/v1/knowledge/** 需要 ADMIN 或 OPS。
 * 未认证直接 40100，角色不足 40300。
 */
@Component
public class RbacInterceptor implements HandlerInterceptor {

    private static final List<String> ADMIN_PREFIXES = List.of("/api/v1/admin/");
    private static final List<String> KNOWLEDGE_PREFIXES = List.of("/api/v1/knowledge/");

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String uri = request.getRequestURI();
        if (!TraceContext.authenticated()) {
            throw BizException.unauthorized("未认证");
        }
        if (matches(uri, ADMIN_PREFIXES)) {
            requireAnyRole("ADMIN");
            return true;
        }
        if (matches(uri, KNOWLEDGE_PREFIXES)) {
            requireAnyRole("ADMIN", "OPS");
        }
        return true;
    }

    private boolean matches(String uri, List<String> prefixes) {
        for (String prefix : prefixes) {
            if (uri.startsWith(prefix)) {
                return true;
            }
        }
        return false;
    }

    private void requireAnyRole(String... roles) {
        for (String role : roles) {
            if (TraceContext.hasRole(role)) {
                return;
            }
        }
        throw BizException.forbidden("需要角色 " + String.join("/", roles));
    }
}
