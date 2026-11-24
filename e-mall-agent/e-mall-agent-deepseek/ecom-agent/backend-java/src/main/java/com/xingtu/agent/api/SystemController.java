package com.xingtu.agent.api;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议
// 职责：系统探针与能力声明（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.api.dto.MetaDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.MilvusRestClient;
import com.xingtu.agent.infra.RedisService;
import com.xingtu.agent.llm.FallbackChain;
import com.xingtu.agent.tool.ToolRegistry;
import org.springframework.amqp.rabbit.connection.Connection;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 系统探针与能力声明（docs/03-API契约.md 第 7 节）。
 *
 * <p>/health 按契约返回裸 JSON（不包 ApiResponse），供 k8s / docker healthcheck 直接消费；
 * 任一组件 DOWN 时 status=DEGRADED，HTTP 仍为 200。/metrics 由 Actuator 的 Prometheus
 * 端点提供（application.yml: management.endpoints.web.path-mapping.prometheus=metrics）。</p>
 */
@RestController
public class SystemController {

    private static final String VERSION = "1.0.0";
    private static final String UP = "UP";
    private static final String DOWN = "DOWN";
    private static final String DISABLED = "DISABLED";

    private final JdbcTemplate jdbc;
    private final RedisService redisService;
    private final MilvusRestClient milvusRestClient;
    private final RabbitTemplate rabbitTemplate;
    private final FallbackChain fallbackChain;
    private final ToolRegistry toolRegistry;
    private final AppProperties props;

    public SystemController(JdbcTemplate jdbc, RedisService redisService,
                            MilvusRestClient milvusRestClient, RabbitTemplate rabbitTemplate,
                            FallbackChain fallbackChain, ToolRegistry toolRegistry,
                            AppProperties props) {
        this.jdbc = jdbc;
        this.redisService = redisService;
        this.milvusRestClient = milvusRestClient;
        this.rabbitTemplate = rabbitTemplate;
        this.fallbackChain = fallbackChain;
        this.toolRegistry = toolRegistry;
        this.props = props;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> components = new LinkedHashMap<>();
        components.put("mysql", mysqlState());
        components.put("redis", redisService.healthy() ? UP : DOWN);
        components.put("rabbitmq", rabbitState());
        components.put("milvus", milvusState());

        boolean degraded = false;
        for (Object state : components.values()) {
            if (DOWN.equals(state)) {
                degraded = true;
                break;
            }
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", degraded ? "DEGRADED" : UP);
        body.put("components", components);
        return body;
    }

    @GetMapping("/api/v1/meta/capabilities")
    public ApiResponse<MetaDtos.CapabilitiesVO> capabilities() {
        Map<String, Boolean> features = new LinkedHashMap<>();
        features.put("mcp", false);
        features.put("skills", false);
        features.put("codeMode", toolRegistry.find("run_python").isPresent());
        features.put("text2sql", toolRegistry.find("text2sql").isPresent());
        features.put("hybridRag", true);
        return ApiResponse.ok(new MetaDtos.CapabilitiesVO("java", VERSION, features,
                new MetaDtos.LlmCapabilityVO(fallbackChain.primaryModel(),
                        fallbackChain.fallbackModels())));
    }

    private String mysqlState() {
        try {
            Integer probe = jdbc.queryForObject("SELECT 1", Integer.class);
            return probe != null && probe == 1 ? UP : DOWN;
        } catch (RuntimeException e) {
            return DOWN;
        }
    }

    private String rabbitState() {
        if (!props.getMq().isEnabled()) {
            return DISABLED;
        }
        Connection connection = null;
        try {
            ConnectionFactory factory = rabbitTemplate.getConnectionFactory();
            if (factory == null) {
                return DOWN;
            }
            connection = factory.createConnection();
            return connection.isOpen() ? UP : DOWN;
        } catch (RuntimeException e) {
            return DOWN;
        } finally {
            if (connection != null) {
                try {
                    connection.close();
                } catch (RuntimeException ignored) {
                    // 探针不允许因为关闭连接失败而影响响应
                }
            }
        }
    }

    private String milvusState() {
        if (!props.getMilvus().isEnabled()) {
            return DISABLED;
        }
        return milvusRestClient.healthy() ? UP : DOWN;
    }
}
