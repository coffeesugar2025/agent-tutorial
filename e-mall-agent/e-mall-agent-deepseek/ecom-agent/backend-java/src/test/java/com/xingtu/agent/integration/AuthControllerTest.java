package com.xingtu.agent.integration;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：认证接口测试：MockMvc standaloneSetup，不起 Spring 容器、不连数据库/Redis， 仓储与
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.api.AuthController;
import com.xingtu.agent.common.GlobalExceptionHandler;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.repo.UserRepository;
import com.xingtu.agent.security.JwtService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 认证接口测试：MockMvc standaloneSetup，不起 Spring 容器、不连数据库/Redis，
 * 仓储与 JWT 之外的一切依赖都为 0。
 */
class AuthControllerTest {

    private UserRepository userRepository;
    private MockMvc mockMvc;
    private String passwordHash;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        AppProperties props = new AppProperties();
        props.getJwt().setSecret("test-secret-key-for-jwt-signing-32bytes!");
        props.getJwt().setExpireSeconds(86_400L);
        JwtService jwtService = new JwtService(props);
        AuthController controller = new AuthController(userRepository, jwtService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        passwordHash = new BCryptPasswordEncoder().encode("Passw0rd!");
        TraceContext.clear();
    }

    @AfterEach
    void tearDown() {
        TraceContext.clear();
    }

    private UserRepository.UserRow alice() {
        return new UserRepository.UserRow(2L, "alice", passwordHash, "Alice", "alice@xingtu.example.com",
                List.of("USER"), 1, LocalDateTime.now());
    }

    @Test
    void loginReturnsTokenAndUser() throws Exception {
        when(userRepository.findByUsername("alice")).thenReturn(alice());
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"Passw0rd!\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.message").value("ok"))
                .andExpect(jsonPath("$.data.token").isNotEmpty())
                .andExpect(jsonPath("$.data.expiresIn").value(86_400))
                .andExpect(jsonPath("$.data.user.username").value("alice"))
                .andExpect(jsonPath("$.data.user.roles[0]").value("USER"));
    }

    @Test
    void wrongPasswordIsUnauthorized() throws Exception {
        when(userRepository.findByUsername("alice")).thenReturn(alice());
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"wrong\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(40100));
    }

    @Test
    void unknownUserIsUnauthorized() throws Exception {
        when(userRepository.findByUsername("ghost")).thenReturn(null);
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"ghost\",\"password\":\"Passw0rd!\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(40100));
    }

    @Test
    void blankCredentialsAreValidationError() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"\",\"password\":\"\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(40001));
    }

    @Test
    void disabledAccountIsForbidden() throws Exception {
        UserRepository.UserRow disabled = new UserRepository.UserRow(3L, "bob", passwordHash, "Bob", null,
                List.of("USER"), 0, LocalDateTime.now());
        when(userRepository.findByUsername("bob")).thenReturn(disabled);
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"bob\",\"password\":\"Passw0rd!\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(40300));
    }

    @Test
    void meReturnsIdentityUser() throws Exception {
        when(userRepository.findById(2L)).thenReturn(alice());
        TraceContext.setTraceId("trace-auth-1");
        TraceContext.setIdentity(2L, "alice", List.of("USER"));
        mockMvc.perform(get("/api/v1/auth/me"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.id").value(2))
                .andExpect(jsonPath("$.data.displayName").value("Alice"))
                .andExpect(jsonPath("$.traceId").value("trace-auth-1"));
    }
}
