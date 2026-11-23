package com.example.ecom.service;

import com.example.ecom.config.LangChain4jConfig;
import com.example.ecom.rag.DocumentIngestor;
import com.zaxxer.hikari.HikariDataSource;
import org.springframework.amqp.rabbit.connection.CachingConnectionFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 依赖健康检查：如实上报 configured / active / backend / detail。
 * 未配置时明确标注 fallback，而不是假装成功。
 */
@Service
public class InfraHealthService {

    private final DataSource dataSource;
    private final ObjectProvider<StringRedisTemplate> redis;
    private final ObjectProvider<CachingConnectionFactory> rabbit;
    private final DocumentIngestor ingestor;
    private final LangChain4jConfig.RoutingChatModel chatModel;

    public InfraHealthService(DataSource dataSource,
                              ObjectProvider<StringRedisTemplate> redis,
                              ObjectProvider<CachingConnectionFactory> rabbit,
                              DocumentIngestor ingestor,
        org.springframework.context.ApplicationContext context) {
        this.dataSource = dataSource;
        this.redis = redis;
        this.rabbit = rabbit;
        this.ingestor = ingestor;
        Object model = context.getBean("chatModel");
        this.chatModel = model instanceof LangChain4jConfig.RoutingChatModel r ? r : null;
    }

    public Map<String, Object> health() {
        Map<String, Object> components = new LinkedHashMap<>();
        components.put("mysql", database());
        components.put("redis", redis());
        components.put("rabbitmq", rabbit());
        components.put("milvus", milvus());
        components.put("llm", llm());
        return Map.of("components", components);
    }

    private Map<String, Object> database() {
        String url = dataSource instanceof HikariDataSource h ? h.getJdbcUrl() : "unknown";
        boolean mysql = url != null && url.startsWith("jdbc:mysql");
        boolean active = false;
        try (Connection c = dataSource.getConnection()) {
            active = c.isValid(1);
        } catch (Exception ignored) {
            // 如实上报
        }
        return component(mysql, active, mysql ? "mysql" : "h2-in-memory",
                active ? "connected" : "connection failed");
    }

    private Map<String, Object> redis() {
        boolean configured = envSet("REDIS_HOST") || envSet("REDIS_URL");
        boolean active = false;
        if (configured) {
            try {
                StringRedisTemplate template = redis.getIfAvailable();
                active = template != null && Boolean.TRUE.equals(template.hasKey("__ecom_health__"));
            } catch (Exception ignored) {
                active = false;
            }
        }
        return component(configured, active, configured ? "redis" : "in-memory",
                configured ? (active ? "pong" : "unreachable") : "fallback: in-memory chat memory");
    }

    private Map<String, Object> rabbit() {
        boolean configured = envSet("RABBITMQ_HOST") || envSet("RABBITMQ_URL");
        boolean active = false;
        if (configured) {
            try {
                CachingConnectionFactory factory = rabbit.getIfAvailable();
                if (factory != null) {
                    factory.createConnection().close();
                    active = true;
                }
            } catch (Exception ignored) {
                active = false;
            }
        }
        return component(configured, active, configured ? "rabbitmq" : "in-memory",
                configured ? (active ? "connected" : "unreachable") : "fallback: in-memory domain events");
    }

    private Map<String, Object> milvus() {
        boolean configured = "true".equalsIgnoreCase(System.getenv("MILVUS_ENABLED"));
        boolean active = ingestor.vectorIngest();
        return component(configured, active, configured ? "milvus" : "in-memory",
                configured ? (active ? "vectors ingested" : "not ready")
                        : "fallback: keyword retrieval over in-memory chunks");
    }

    private Map<String, Object> llm() {
        boolean deepseek = envSet("DEEPSEEK_API_KEY");
        boolean qwen = envSet("QWEN_API_KEY");
        boolean configured = deepseek || qwen;
        String backend = chatModel == null ? "offline" : String.valueOf(chatModel.provider());
        return component(configured, configured, backend,
                configured ? "OpenAI-compatible endpoint configured" : "fallback: rule-based answers");
    }

    private static boolean envSet(String name) {
        String value = System.getenv(name);
        return value != null && !value.isBlank();
    }

    private static Map<String, Object> component(boolean configured, boolean active,
                                                 String backend, String detail) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("configured", configured);
        m.put("active", active);
        m.put("backend", backend);
        m.put("detail", detail);
        return m;
    }
}
