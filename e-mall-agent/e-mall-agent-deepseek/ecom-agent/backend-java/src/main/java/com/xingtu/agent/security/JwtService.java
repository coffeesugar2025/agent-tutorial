package com.xingtu.agent.security;

// ═══════ 文件级能力标注 ═══════
// [CAP-15] 安全与合规
// 职责：JWT 签发与校验（jjwt 0
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.config.AppProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

/**
 * JWT 签发与校验（jjwt 0.12.x API）。
 * payload: {"sub":"<userId>","username":"...","roles":["USER"],"exp":...}
 */
@Component
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);
    private static final int MIN_KEY_BYTES = 32;

    private final SecretKey key;
    private final long expireSeconds;

    public JwtService(AppProperties props) {
        this.key = Keys.hmacShaKeyFor(normalizeSecret(props.getJwt().getSecret()));
        this.expireSeconds = Math.max(60L, props.getJwt().getExpireSeconds());
    }

    public String issue(long userId, String username, List<String> roles) {
        long now = System.currentTimeMillis();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .claim("username", username)
                .claim("roles", roles == null ? List.of("USER") : roles)
                .issuedAt(new Date(now))
                .expiration(new Date(now + expireSeconds * 1000L))
                .signWith(key)
                .compact();
    }

    public long expiresInSeconds() {
        return expireSeconds;
    }

    /** 解析并注入 TraceContext；失败抛 40100。 */
    public void authenticate(String token) {
        Claims claims = parse(token);
        long userId;
        try {
            userId = Long.parseLong(claims.getSubject());
        } catch (NumberFormatException e) {
            throw BizException.unauthorized("token 中缺少合法的用户标识");
        }
        Object username = claims.get("username");
        TraceContext.setIdentity(userId, username == null ? "" : String.valueOf(username), roles(claims));
    }

    public Claims parse(String token) {
        try {
            return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
        } catch (JwtException e) {
            log.debug("JWT 校验失败: {}", e.getMessage());
            throw BizException.unauthorized("token 无效或已过期");
        } catch (IllegalArgumentException e) {
            throw BizException.unauthorized("token 格式错误");
        }
    }

    private List<String> roles(Claims claims) {
        List<String> roles = new ArrayList<>();
        Object raw = claims.get("roles");
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    roles.add(String.valueOf(item));
                }
            }
        } else if (raw instanceof String text) {
            for (String item : text.split(",")) {
                if (!item.isBlank()) {
                    roles.add(item.trim());
                }
            }
        }
        if (roles.isEmpty()) {
            roles.add("USER");
        }
        return roles;
    }

    private byte[] normalizeSecret(String secret) {
        String value = secret == null || secret.isBlank() ? "change-me-in-prod" : secret;
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        if (bytes.length >= MIN_KEY_BYTES) {
            return bytes;
        }
        byte[] padded = new byte[MIN_KEY_BYTES];
        for (int i = 0; i < MIN_KEY_BYTES; i++) {
            padded[i] = i < bytes.length ? bytes[i] : (byte) ('0' + (i % 10));
        }
        return padded;
    }
}
