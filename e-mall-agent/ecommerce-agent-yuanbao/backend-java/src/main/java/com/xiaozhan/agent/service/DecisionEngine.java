package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/** 第 0 章：判据 / L0-L4 / ROI / 决策树 / 误区自查，与 Python 侧同语义。 */
@Service
public class DecisionEngine {
    public record TaskProfile(String name, boolean decomposable, boolean verifiableFeedback,
                              boolean reversible, double errorCost, int callFrequency,
                              int latencySlaMs, boolean contextAvailable, boolean longTail,
                              boolean auditRequired) {}

    public Map<String, Object> fit(TaskProfile t) {
        List<String> blockers = new java.util.ArrayList<>();
        if (!t.decomposable()) blockers.add("不可分解");
        if (!t.verifiableFeedback()) blockers.add("无可验证反馈信号");
        if (!t.contextAvailable()) blockers.add("运行时拿不到所需上下文");
        if (!t.longTail()) blockers.add("规则可穷举 → 用规则引擎");
        if (t.auditRequired() && t.errorCost() > 0.7) blockers.add("强审计+高错误成本 → Workflow");
        if (t.latencySlaMs() < 300 && t.callFrequency() > 10000) blockers.add("极低延迟+高频");
        double score = (List.of(t.decomposable(), t.verifiableFeedback(), t.reversible(),
                t.contextAvailable(), t.longTail()).stream().filter(b -> b).count()) / 5.0;
        boolean fit = blockers.isEmpty() && score >= 0.6;
        return Map.of("fit", fit, "score", score, "blockers", blockers,
                "recommendation", fit ? "Agent" : "Workflow/规则/单模型调用");
    }

    public List<Map<String, String>> autonomyLevels() {
        return List.of(Map.of("level", "L0", "name", "纯生成", "blast_radius", "单条回答"),
                Map.of("level", "L1", "name", "单轮工具调用", "blast_radius", "一次只读调用"),
                Map.of("level", "L2", "name", "多步自主循环", "blast_radius", "多工具+token 成本"),
                Map.of("level", "L3", "name", "长时任务+人工审批", "blast_radius", "可能触发写操作"),
                Map.of("level", "L4", "name", "多 Agent 自治", "blast_radius", "成本与错误传播最大"));
    }

    public Map<String, Object> roi(double inference, double successRate, double humanRate,
                                   double humanCost, int callsPerDay) {
        double eff = inference / Math.max(1e-9, successRate) + humanRate * humanCost;
        return Map.of("effective_cost_per_task", eff, "daily_cost", eff * callsPerDay,
                "formula", "单任务推理成本 / 成功率 + 人工兜底成本");
    }

    public Map<String, Object> architectureTree(TaskProfile t) {
        String choice;
        if (!t.decomposable()) choice = "单次调用 / 链式 Prompt";
        else if (!t.longTail()) choice = "Workflow / DAG（路径确定、可审计）";
        else if (!t.verifiableFeedback()) choice = "单 Agent + 只读工具 + 强校验";
        else if (t.errorCost() > 0.7 || t.auditRequired()) choice = "Workflow + HITL 审批点";
        else choice = "单 Agent（默认）；仅确有上下文隔离需求才上 Supervisor";
        return Map.of("choice", choice, "default_bias", "workflow > single-agent > multi-agent");
    }

    public List<Map<String, String>> misconceptions() {
        return List.of(Map.of("myth", "Agent 越多越强", "correction", "多数场景正确解是单 Agent + 好工具 + 好流程"),
                Map.of("myth", "RAG 能消除幻觉", "correction", "RAG 会引入错召回/错引用/资料过期的新幻觉"),
                Map.of("myth", "一次评测通过=生产可用", "correction", "要看 pass^k（k 次全对）"));
    }
}
