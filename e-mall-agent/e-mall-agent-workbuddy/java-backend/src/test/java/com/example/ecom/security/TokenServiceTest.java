package com.example.ecom.security;

import com.example.ecom.domain.User;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class TokenServiceTest {

    private final TokenService tokens = new TokenService(new ObjectMapper(), "test-secret", 3600);

    @Test
    void issueAndVerifyRoundTrip() {
        String token = tokens.issue(new User("u-1", "张三", "customer"));
        User user = tokens.verify(token);
        assertNotNull(user);
        assertEquals("u-1", user.getId());
        assertEquals("张三", user.getName());
        assertEquals("customer", user.getRole());
    }

    @Test
    void rejectsTamperedToken() {
        String token = tokens.issue(new User("u-1", "张三", "customer"));
        String tampered = token.substring(0, token.length() - 2)
                + (token.endsWith("AA") ? "BB" : "AA");
        assertNull(tokens.verify(tampered));
    }

    @Test
    void rejectsMalformedToken() {
        assertNull(tokens.verify("not-a-token"));
        assertNull(tokens.verify(null));
        assertNull(tokens.verify(""));
    }

    @Test
    void rejectsExpiredToken() {
        TokenService shortLived = new TokenService(new ObjectMapper(), "test-secret", -10);
        String token = shortLived.issue(new User("u-1", "张三", "customer"));
        assertNull(shortLived.verify(token));
    }
}
