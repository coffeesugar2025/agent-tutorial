package com.example.ecom.service;

import com.example.ecom.domain.User;
import com.example.ecom.repository.AuditLogRepository;
import com.example.ecom.repository.UserRepository;
import com.example.ecom.security.ApiException;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.security.TokenService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class AuthService {

    private final UserRepository users;
    private final TokenService tokens;
    private final RbacGuard rbac;
    private final AuditLogRepository audits;

    public AuthService(UserRepository users, TokenService tokens, RbacGuard rbac, AuditLogRepository audits) {
        this.users = users;
        this.tokens = tokens;
        this.rbac = rbac;
        this.audits = audits;
    }

    /** 返回契约要求的 {token, user:{id,name,role}}，并附带现有前端使用的扁平字段。 */
    public Map<String, Object> login(String username, String password) {
        // 统一契约：登录名可以是显示名（张三），也可以是用户 ID（U001）
        User user = users.findByName(username)
                .orElseGet(() -> users.findById(username).orElse(null));
        if (user == null || user.getPassword() == null || !user.getPassword().equals(password)) {
            audits.save(new com.example.ecom.domain.AuditLog(
                    username == null ? "unknown" : username, "auth.login", "token", "deny", "凭证错误"));
            throw new ApiException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }
        String token = tokens.issue(user);
        audits.save(new com.example.ecom.domain.AuditLog(user.getId(), "auth.login", "token", "allow", ""));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("token", token);
        result.put("user", Map.of("id", user.getId(), "name", user.getName(), "role", user.getRole()));
        result.put("user_id", user.getId());
        result.put("role", user.getRole());
        result.put("permissions", rbac.permissionsFor(user.getRole()));
        return result;
    }
}
