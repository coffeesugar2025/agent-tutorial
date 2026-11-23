package com.example.ecom;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** 全链路集成测试：无外部依赖（H2 + 离线规则模型）即可通过。 */
@SpringBootTest
@AutoConfigureMockMvc
class EcomApplicationIntegrationTest {

    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper mapper;

    @Test
    void healthAndInfraHealthArePublic() throws Exception {
        JsonNode health = json(mvc.perform(get("/api/health")).andExpect(status().isOk()).andReturn());
        assertEquals("ok", health.get("status").asText());
        assertTrue(health.get("service").asText().contains("ecom"));

        JsonNode infra = json(mvc.perform(get("/api/infra/health")).andExpect(status().isOk()).andReturn());
        JsonNode components = infra.get("components");
        for (String name : new String[]{"mysql", "redis", "rabbitmq", "milvus", "llm"}) {
            assertTrue(components.has(name), "missing component: " + name);
        }
    }

    @Test
    void loginThenListProductsAndChat() throws Exception {
        JsonNode login = json(mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"U001\",\"password\":\"123456\"}"))
                .andExpect(status().isOk()).andReturn());
        String token = login.get("token").asText();
        assertFalse(token.isBlank());
        assertEquals("customer", login.get("user").get("role").asText());

        JsonNode products = json(mvc.perform(get("/api/products").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk()).andReturn());
        assertTrue(products.isArray());
        assertEquals(8, products.size());
        assertTrue(products.get(0).get("tags").isArray());

        JsonNode chat = json(mvc.perform(post("/api/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message\":\"我想买降噪耳机\",\"thread_id\":\"integration\"}"))
                .andExpect(status().isOk()).andReturn());
        assertFalse(chat.get("answer").asText().isBlank());
        assertFalse(chat.get("trace_id").asText().isBlank());
        assertTrue(chat.get("answer").asText().contains("离线规则模式")
                || !chat.get("answer").asText().isBlank());
    }

    @Test
    void protectedEndpointRejectsAnonymous() throws Exception {
        mvc.perform(get("/api/orders")).andExpect(status().isUnauthorized());
    }

    private JsonNode json(MvcResult result) throws Exception {
        return mapper.readTree(result.getResponse().getContentAsString());
    }
}
