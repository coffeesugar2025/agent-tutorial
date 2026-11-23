package com.example.ecom.security;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.ecom.domain.User;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;

/**
 * 轻量 HMAC-SHA256 Token（不引入 Spring Security 全家桶）。
 * 格式：base64url(payloadJson).base64url(HMAC_SHA256(payloadJson))
 * payload 包含 sub/name/role/iat/exp，Bearer 头解析后得到 user/role。
 */
@Component
public class TokenService {

    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();
    private static final String ALGORITHM = "HmacSHA256";

    private final ObjectMapper mapper;
    private final byte[] secret;
    private final long ttlSeconds;

    public TokenService(ObjectMapper mapper,
                        @Value("${app.security.secret:ecom-dev-secret-change-me}") String secret,
                        @Value("${app.security.token-ttl-seconds:86400}") long ttlSeconds) {
        this.mapper = mapper;
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.ttlSeconds = ttlSeconds;
    }

    public String issue(User user) {
        long now = Instant.now().getEpochSecond();
        Map<String, Object> payload = Map.of(
                "sub", user.getId(),
                "name", user.getName() == null ? "" : user.getName(),
                "role", user.getRole() == null ? "guest" : user.getRole(),
                "iat", now,
                "exp", now + ttlSeconds
        );
        try {
            String json = mapper.writeValueAsString(payload);
            String body = ENCODER.encodeToString(json.getBytes(StandardCharsets.UTF_8));
            return body + "." + ENCODER.encodeToString(sign(json));
        } catch (Exception e) {
            throw new IllegalStateException("签发 Token 失败", e);
        }
    }

    /** 校验签名与过期时间；无效返回 null。 */
    public User verify(String token) {
        if (token == null || token.isBlank()) return null;
        String[] parts = token.split("\\.", 2);
        if (parts.length != 2) return null;
        try {
            String json = new String(DECODER.decode(parts[0]), StandardCharsets.UTF_8);
            byte[] expected = sign(json);
            byte[] actual = DECODER.decode(parts[1]);
            if (!MessageDigest.isEqual(expected, actual)) return null;

            Map<String, Object> payload = mapper.readValue(json, new TypeReference<>() {});
            Object exp = payload.get("exp");
            if (exp instanceof Number n && n.longValue() < Instant.now().getEpochSecond()) return null;

            String id = String.valueOf(payload.getOrDefault("sub", "anonymous"));
            String name = String.valueOf(payload.getOrDefault("name", ""));
            String role = String.valueOf(payload.getOrDefault("role", "guest"));
            return new User(id, name, role);
        } catch (Exception e) {
            return null;
        }
    }

    private byte[] sign(String data) throws Exception {
        Mac mac = Mac.getInstance(ALGORITHM);
        mac.init(new SecretKeySpec(secret, ALGORITHM));
        return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
    }
}
