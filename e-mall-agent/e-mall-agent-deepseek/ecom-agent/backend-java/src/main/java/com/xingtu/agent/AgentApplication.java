package com.xingtu.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  （支撑）
// 职责：电商智能体 Java 后端入口
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableAsync;

/**
 * 电商智能体 Java 后端入口。
 *
 * <p>与 Python 端共享 docs/03-API契约.md 与同一份 MySQL/Milvus 结构；
 * 全链路可通过 LLM_PRIMARY=mock + EMBEDDING_PROVIDER=hash 离线跑通。</p>
 */
@SpringBootApplication
@EnableAsync
@EnableConfigurationProperties(AppProperties.class)
public class AgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentApplication.class, args);
    }
}
