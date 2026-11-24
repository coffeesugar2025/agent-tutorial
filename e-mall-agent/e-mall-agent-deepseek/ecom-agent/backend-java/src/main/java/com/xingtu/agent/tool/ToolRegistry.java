package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：工具注册表：集中登记工具名、描述、风险级别与执行器
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 工具注册表：集中登记工具名、描述、风险级别与执行器。
 * AgentRuntime 只通过这里取工具定义与执行工具，工具与 Agent 解耦。
 */
@Component
public class ToolRegistry {

    @FunctionalInterface
    public interface Handler {
        ToolResult execute(Map<String, Object> args, ToolContext context);
    }

    public record Definition(String name, String description, ToolRisk risk, List<String> agents,
                             Handler handler) {
    }

    private final Map<String, Definition> tools = new LinkedHashMap<>();

    // ──────── [CAP-05] 工具治理 ────────
    //   本处：声明式注册
    //   域约束：READ 可重试、WRITE 幂等、IRREVERSIBLE 必须走审批；新增工具只注册不改管线
    public void register(Definition definition) {
        if (definition == null || definition.name() == null) {
            return;
        }
        tools.put(definition.name(), definition);
    }

    public Optional<Definition> find(String name) {
        return Optional.ofNullable(tools.get(name));
    }

    // ──────── [CAP-05] 工具治理 ────────
    //   本处：风险分级查询
    //   域约束：READ 可重试、WRITE 幂等、IRREVERSIBLE 必须走审批；新增工具只注册不改管线
    public ToolRisk riskOf(String name) {
        Definition definition = tools.get(name);
        return definition == null ? ToolRisk.READ : definition.risk();
    }

    public Set<String> names() {
        return tools.keySet();
    }

    public List<Definition> forAgent(String agentType) {
        List<Definition> result = new ArrayList<>();
        for (Definition definition : tools.values()) {
            if (definition.agents().isEmpty() || definition.agents().contains(agentType)) {
                result.add(definition);
            }
        }
        return result;
    }

    /** 生成注入 prompt 的工具清单（只暴露给当前 Agent 的工具）。 */
    public String catalog(String agentType) {
        StringBuilder sb = new StringBuilder();
        for (Definition definition : forAgent(agentType)) {
            sb.append("- ").append(definition.name()).append(" (").append(definition.risk())
                    .append("): ").append(definition.description()).append('\n');
        }
        return sb.toString();
    }

    /** 执行工具并统一计时；未注册的工具返回失败而不是抛异常。 */
    public ToolResult execute(String name, Map<String, Object> args, ToolContext context) {
        Definition definition = tools.get(name);
        if (definition == null) {
            return ToolResult.fail("未注册的工具: " + name);
        }
        long start = System.currentTimeMillis();
        try {
            ToolResult result = definition.handler().execute(args == null ? Map.of() : args, context);
            return result.withLatency(System.currentTimeMillis() - start);
        } catch (BizException e) {
            return ToolResult.fail(e.getMessage()).withLatency(System.currentTimeMillis() - start);
        } catch (RuntimeException e) {
            return ToolResult.fail("工具执行异常: " + e.getMessage())
                    .withLatency(System.currentTimeMillis() - start);
        }
    }

    public int size() {
        return tools.size();
    }
}
