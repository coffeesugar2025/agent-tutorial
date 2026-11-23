package com.xingtu.agent.api.dto;

import java.util.List;

/**
 * 认证相关 DTO（docs/03-API契约.md 第 1 节）。字段名即 JSON 字段名（Jackson 驼峰）。
 */
public final class AuthDtos {

    private AuthDtos() {
    }

    /** POST /api/v1/auth/login 请求体。 */
    public record LoginReq(String username, String password) {
    }

    /** 用户对象：登录响应与 /auth/me 共用。 */
    public record UserVO(long id, String username, String displayName, List<String> roles) {
    }

    /** 登录响应 data。 */
    public record LoginVO(String token, long expiresIn, UserVO user) {
    }
}
