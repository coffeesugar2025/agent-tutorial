package com.xingtu.agent.api;

import com.xingtu.agent.api.dto.AuthDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.infra.repo.UserRepository;
import com.xingtu.agent.security.JwtService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 认证接口（docs/03-API契约.md 第 1 节）。
 *
 * <p>白名单由 AuthFilter 控制：/api/v1/auth/login 免认证，/api/v1/auth/me 需要 Bearer JWT。</p>
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final UserRepository userRepository;
    private final JwtService jwtService;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    public AuthController(UserRepository userRepository, JwtService jwtService) {
        this.userRepository = userRepository;
        this.jwtService = jwtService;
    }

    @PostMapping("/login")
    public ApiResponse<AuthDtos.LoginVO> login(@RequestBody(required = false) AuthDtos.LoginReq req) {
        if (req == null || req.username() == null || req.username().isBlank()
                || req.password() == null || req.password().isBlank()) {
            throw BizException.validation("username 和 password 不能为空");
        }
        UserRepository.UserRow user = userRepository.findByUsername(req.username().trim());
        if (user == null || !matches(req.password(), user.passwordHash())) {
            throw BizException.unauthorized("用户名或密码错误");
        }
        if (user.status() != 1) {
            throw BizException.forbidden("账号已被禁用");
        }
        List<String> roles = user.roles() == null || user.roles().isEmpty() ? List.of("USER") : user.roles();
        String token = jwtService.issue(user.id(), user.username(), roles);
        return ApiResponse.ok(new AuthDtos.LoginVO(token, jwtService.expiresInSeconds(),
                new AuthDtos.UserVO(user.id(), user.username(), user.displayName(), roles)));
    }

    @GetMapping("/me")
    public ApiResponse<AuthDtos.UserVO> me() {
        TraceContext.Identity identity = TraceContext.identity();
        if (identity == null) {
            throw BizException.unauthorized("未认证");
        }
        UserRepository.UserRow user = userRepository.findById(identity.userId());
        if (user != null) {
            List<String> roles = user.roles() == null || user.roles().isEmpty()
                    ? identity.roles() : user.roles();
            return ApiResponse.ok(new AuthDtos.UserVO(user.id(), user.username(), user.displayName(),
                    roles));
        }
        // 用户被删除但 token 仍有效：回退到 JWT 中的声明，避免 500。
        return ApiResponse.ok(new AuthDtos.UserVO(identity.userId(), identity.username(),
                identity.username(), identity.roles()));
    }

    private boolean matches(String rawPassword, String passwordHash) {
        if (passwordHash == null || passwordHash.isBlank()) {
            return false;
        }
        try {
            return passwordEncoder.matches(rawPassword, passwordHash);
        } catch (IllegalArgumentException e) {
            return false;
        }
    }
}
