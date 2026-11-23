package com.example.ecom.security;

import com.example.ecom.domain.User;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.Set;

/** 最小权限模型：三级角色 customer / service / admin + guest。 */
@Component
public class RbacGuard {

    public static final Map<String, Set<String>> ROLE_PERMISSIONS = Map.of(
            "guest", Set.of("product:read", "chat:use"),
            "customer", Set.of("product:read", "chat:use", "order:read", "order:create", "order:refund"),
            "service", Set.of("product:read", "chat:use", "order:read", "order:create", "order:refund",
                    "order:manage", "audit:read", "trace:read"),
            "admin", Set.of("product:read", "chat:use", "order:read", "order:create", "order:refund",
                    "order:manage", "audit:read", "trace:read", "frontier:use", "scan:run")
    );

    /** 工具白名单：LLM 只能调用角色允许的工具。 */
    private static final Map<String, Set<String>> TOOL_WHITELIST = Map.of(
            "guest", Set.of("searchProducts", "checkStock"),
            "customer", Set.of("searchProducts", "checkStock", "createOrder", "listOrders", "requestRefund"),
            "service", Set.of("searchProducts", "checkStock", "listOrders", "requestRefund"),
            "admin", Set.of("searchProducts", "checkStock", "createOrder", "listOrders", "requestRefund")
    );

    public List<String> permissionsFor(String role) {
        return List.copyOf(ROLE_PERMISSIONS.getOrDefault(normalize(role), Set.of()));
    }

    public boolean hasPermission(User user, String permission) {
        if (user == null) return false;
        return ROLE_PERMISSIONS.getOrDefault(normalize(user.getRole()), Set.of()).contains(permission);
    }

    public void require(User user, String permission) {
        if (user == null || "guest".equals(normalize(user.getRole()))) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "需要登录");
        }
        if (!hasPermission(user, permission)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "需要权限: " + permission);
        }
    }

    public boolean toolAllowed(String role, String toolName) {
        return TOOL_WHITELIST.getOrDefault(normalize(role), Set.of()).contains(toolName);
    }

    /** 客户只能看自己的订单；客服/管理员可跨客户查询。 */
    public void requireCustomerScope(User user, String customerId) {
        if (user == null) throw new ApiException(HttpStatus.UNAUTHORIZED, "需要登录");
        if ("customer".equals(normalize(user.getRole())) && !user.getId().equals(customerId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "只能访问自己的订单");
        }
    }

    public static String normalize(String role) {
        return role == null || role.isBlank() ? "guest" : role.toLowerCase();
    }
}
