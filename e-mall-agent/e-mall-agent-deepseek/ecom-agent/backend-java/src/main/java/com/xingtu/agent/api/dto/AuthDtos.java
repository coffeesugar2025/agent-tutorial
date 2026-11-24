package com.xingtu.agent.api.dto;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  （支撑）
// 职责：认证相关 DTO（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

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
