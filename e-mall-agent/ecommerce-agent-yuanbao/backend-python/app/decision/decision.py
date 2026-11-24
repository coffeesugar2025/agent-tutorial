"""第 0 章全量落地：判据 / 分级 / ROI / 决策树 / 形态 / 误区自查。

这是上一轮审计里第 0 章「零覆盖」的补齐，全部是可执行函数而非文档口号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskProfile:
    name: str
    decomposable: bool
    verifiable_feedback: bool
    reversible: bool
    error_cost: float            # 0=可忽略 1=灾难
    call_frequency: int          # 次/天
    latency_sla_ms: int
    context_available: bool
    long_tail: bool              # 规则能否穷举的反面
    audit_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def agent_fit(task: TaskProfile) -> dict[str, Any]:
    """任务可 Agent 化判据（0.2）。反向指标直接一票否决。"""
    blockers = []
    if not task.decomposable:
        blockers.append("不可分解")
    if not task.verifiable_feedback:
        blockers.append("无可验证反馈信号")
    if not task.context_available:
        blockers.append("运行时拿不到所需上下文")
    if not task.long_tail:
        blockers.append("规则可穷举 → 用规则引擎")
    if task.audit_required and task.error_cost > 0.7:
        blockers.append("强审计 + 高错误成本 → 用固定 Workflow")
    if task.latency_sla_ms < 300 and task.call_frequency > 10000:
        blockers.append("极低延迟 + 高频 → 不该上 Agent")
    score = sum([task.decomposable, task.verifiable_feedback, task.reversible,
                 task.context_available, task.long_tail]) / 5.0
    return {"fit": not blockers and score >= 0.6, "score": round(score, 4),
            "blockers": blockers,
            "recommendation": "Agent" if not blockers and score >= 0.6 else "Workflow/规则/单模型调用"}


LEVELS = [
    {"level": "L0", "name": "纯生成", "autonomy": "无工具无循环",
     "responsibility": "完全由提示词负责", "blast_radius": "单条回答"},
    {"level": "L1", "name": "单轮工具调用", "autonomy": "模型选一次工具",
     "responsibility": "工具参数由模型负责", "blast_radius": "一次只读调用"},
    {"level": "L2", "name": "多步自主循环", "autonomy": "模型决定下一步",
     "responsibility": "需终止条件与预算", "blast_radius": "多工具调用 + token 成本"},
    {"level": "L3", "name": "长时任务 + 人工审批", "autonomy": "可持久可恢复",
     "responsibility": "审批人共担", "blast_radius": "可能触发写操作"},
    {"level": "L4", "name": "多 Agent 自治", "autonomy": "分派与协作",
     "responsibility": "责任归属最难界定", "blast_radius": "成本与错误传播最大"},
]


def autonomy_levels() -> list[dict[str, Any]]:
    return LEVELS


PRODUCT_FORMS = {
    "Copilot": {"who_proposes": "AI", "who_approves": "人", "sync": "同步", "interruptible": True},
    "Chat": {"who_proposes": "人提问", "who_approves": "人", "sync": "流式", "interruptible": True},
    "Autonomous": {"who_proposes": "AI", "who_approves": "AI+审批点", "sync": "异步", "interruptible": False},
    "Embedded": {"who_proposes": "系统", "who_approves": "系统", "sync": "批处理", "interruptible": False},
}


def roi(inference_per_task: float, success_rate: float, human_rate: float,
        human_cost: float, calls_per_day: int) -> dict[str, Any]:
    """有效成本 = 单任务推理成本 / 成功率 + 人工兜底成本（0.5）。"""
    eff = inference_per_task / max(1e-9, success_rate) + human_rate * human_cost
    return {"inference_per_task": round(inference_per_task, 6),
            "success_rate": success_rate,
            "effective_cost_per_task": round(eff, 6),
            "daily_cost": round(eff * calls_per_day, 2),
            "break_even_success_rate": round(inference_per_task / max(1e-9, eff), 4),
            "note": "成功率从 0.8→0.9 的边际收益，要换算成省下的人工兜底费再决定要不要投"}


def architecture_tree(task: TaskProfile) -> dict[str, Any]:
    """选型决策树（0.6）：默认倾向 workflow，而非 multi-agent。"""
    steps: list[str] = []
    if not task.decomposable:
        choice = "单次调用 / 链式 Prompt"
    elif not task.long_tail:
        choice = "Workflow / DAG（路径确定、可审计、成本可控）"
    elif not task.verifiable_feedback:
        choice = "单 Agent + 只读工具 + 强校验"
    elif task.error_cost > 0.7 or task.audit_required:
        choice = "Workflow + HITL 审批点（不引入多 Agent）"
    else:
        choice = "单 Agent（默认）；仅当确有独立领域上下文隔离需求才上 Supervisor"
    steps.append(f"decomposable={task.decomposable} → long_tail={task.long_tail} → "
                 f"verifiable={task.verifiable_feedback} → error_cost={task.error_cost}")
    return {"choice": choice, "default_bias": "workflow > single-agent > multi-agent",
            "exit_condition": "当多 Agent 带来的隔离收益 < 其成本/延迟/归因开销时立即回退",
            "path": steps}


MISCONCEPTIONS = [
    ("Agent 越多越强", "多数场景正确解是：单 Agent + 好工具 + 好流程"),
    ("步数越多越准", "循环每一圈都在烧 token/时间/耐心，必须每轮有信息增量"),
    ("长 Prompt 能解决一切", "长 Prompt 是上下文污染源，规则互相冲突会淹没指令"),
    ("RAG 能消除幻觉", "RAG 会引入新的幻觉：错召回、错引用、资料本身过期"),
    ("上了 Agent 就能替代人工流程", "高错误成本环节仍需 HITL 与兜底"),
    ("一次评测通过 = 生产可用", "要看 pass^k（k 次全对），不是 pass@k"),
]


def misconception_check(answers: list[bool] | None = None) -> dict[str, Any]:
    answers = answers or [False] * len(MISCONCEPTIONS)
    return {"total": len(MISCONCEPTIONS),
            "items": [{"myth": m, "correction": c,
                       "you_agree_with_myth": bool(answers[i])}
                      for i, (m, c) in enumerate(MISCONCEPTIONS)],
            "risk_count": sum(1 for a in answers if a)}


def evaluate_scenarios() -> dict[str, Any]:
    cases = [
        TaskProfile("电商导购问答", True, True, True, 0.2, 50000, 2000, True, True),
        TaskProfile("财务对账入账", True, True, False, 0.95, 200, 60000, True, False, True),
        TaskProfile("固定格式发票开具", True, True, True, 0.3, 100000, 100, True, False, True),
    ]
    return {"scenarios": [{"task": c.name, "fit": agent_fit(c),
                           "architecture": architecture_tree(c)["choice"]} for c in cases]}
