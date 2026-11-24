package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Set;

/** 4.7 / 5.3：检索层 ACL 先过滤再检索，身份来自可信 header 而非模型自述。 */
@Service
public class AclService {
    public record Principal(String userId, String tenantId, Set<String> roles) {}

    public Map<String, Object> filter(Principal p, List<Map<String, Object>> chunks) {
        var visible = chunks.stream().filter(c -> {
            Object meta = c.getOrDefault("meta", Map.of());
            @SuppressWarnings("unchecked") Map<String, Object> m = (Map<String, Object>) meta;
            String tenant = String.valueOf(m.getOrDefault("acl_tenant", "t_default"));
            Object rolesObj = m.getOrDefault("acl_roles", List.of("user"));
            List<String> allowed = rolesObj instanceof List ? (List<String>) rolesObj
                    : List.of(String.valueOf(rolesObj).split(","));
            if (!tenant.equals(p.tenantId())) return false;
            return allowed.stream().anyMatch(p.roles()::contains);
        }).toList();
        return Map.of("input", chunks.size(), "visible", visible.size(),
                "filtered_out", chunks.size() - visible.size(), "chunks", visible,
                "milvus_expr", milvusExpr(p));
    }

    public String milvusExpr(Principal p) {
        return "acl_tenant == \"" + p.tenantId() + "\" and acl_roles in ["
                + String.join(",", p.roles().stream().map(r -> "\"" + r + "\"").toList()) + "]";
    }
}
