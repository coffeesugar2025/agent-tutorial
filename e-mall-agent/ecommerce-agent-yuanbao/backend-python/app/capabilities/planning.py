"""Planning / ReAct / Plan-and-Solve。

三种编排范式并存，全部可离线跑（工具来自 catalog 纯函数，不依赖 MCP 连接）：

  plan()          生成 Plan（步骤列表 + 依赖 + 工具提示）
  react_loop()    Thought → Action → Observation 循环，带终止条件与重复检测
  plan_and_solve() 先规划再逐步执行，失败可重规划（revision）

与 create_agent 的关系：create_agent 是「模型自主选工具」的隐式循环；
这里把循环显式化、可观测、可回放，适合长任务与审计场景。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services import catalog

ToolFn = Callable[..., dict[str, Any]]


def default_tools() -> dict[str, ToolFn]:
    """把领域函数包装成可直接调用的工具表（与 MCP 工具同名，便于对照）。"""
    return {
        "search_products": catalog.search_products,
        "get_product": catalog.get_product,
        "check_inventory": catalog.check_inventory,
        "get_order": catalog.get_order,
        "list_user_orders": catalog.list_user_orders,
        "list_coupons": catalog.list_coupons,
        "calculate_price": catalog.calculate_price,
        "get_after_sale_policy": catalog.get_after_sale_policy,
        "check_after_sale_eligibility": catalog.check_after_sale_eligibility,
        "recommend_products": catalog.recommend_products,
    }


@dataclass
class PlanStep:
    id: int
    description: str
    tool: str
    args: dict[str, Any]
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"          # pending / done / failed / skipped
    observation: str = ""
    error: str = ""


@dataclass
class Plan:
    goal: str
    strategy: str                    # react | plan_and_solve
    steps: list[PlanStep]
    revision: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "strategy": self.strategy, "revision": self.revision,
            "steps": [
                {"id": s.id, "description": s.description, "tool": s.tool, "args": s.args,
                 "depends_on": s.depends_on, "status": s.status,
                 "observation": s.observation[:300], "error": s.error}
                for s in self.steps
            ],
        }


@dataclass
class TraceEntry:
    index: int
    thought: str
    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    observation: str = ""


@dataclass
class PlanResult:
    goal: str
    strategy: str
    plan: dict[str, Any]
    trace: list[dict[str, Any]]
    answer: str
    steps_executed: int
    terminated_by: str
    elapsed_ms: int


def plan(goal: str, strategy: str = "plan_and_solve") -> Plan:
    """规则 Planner：真实实现可替换为 LLM Planner，接口不变。

    优先级：售后 > 订单 > 算价 > 推荐 > 检索；推荐与售后是多步骤编排。
    """
    q = goal.strip()
    steps: list[PlanStep] = []

    def add(desc, tool, args, deps=None):
        steps.append(PlanStep(id=len(steps) + 1, description=desc, tool=tool,
                              args=args, depends_on=deps or []))

    if any(k in q for k in ("退货", "能退", "退款", "售后资格", "保修")):
        add("判定退货资格", "check_after_sale_eligibility",
            {"order_id": "EC20261105002", "user_id": "u_1001"})
        add("查询官方退货政策", "get_after_sale_policy", {"topic": "退货"})
    elif any(k in q for k in ("订单", "物流", "快递", "单号", "签收")):
        add("查询订单状态与物流", "get_order",
            {"order_id": "EC20261118001", "user_id": "u_1001"})
    elif any(k in q for k in ("多少钱", "到手", "用券", "券后", "优惠")):
        add("核验商品库存", "check_inventory", {"sku": "SKU-1001"})
        add("计算到手价", "calculate_price",
            {"sku": "SKU-1001", "quantity": 1, "coupon_code": "FULL100"}, deps=[1])
    elif any(k in q for k in ("推荐", "预算", "帮我挑", "想买")):
        add("按预算召回有货商品", "recommend_products", {"budget": 500.0, "preference": ""})
        add("查询可用优惠券", "list_coupons", {"user_id": "u_1001"})
    elif any(k in q for k in ("库存", "有货", "缺货", "剩几件")):
        add("查询实时库存", "check_inventory", {"sku": "SKU-1001"})
    else:
        add("检索商品", "search_products", {"keyword": _keyword(q), "limit": 3})

    return Plan(goal=q, strategy=strategy, steps=steps)


def _keyword(q: str) -> str:
    for k in ("耳机", "键盘", "风扇", "枕头", "乳胶", "降噪", "数码", "家居"):
        if k in q:
            return k
    return ""


def _summarize(tool: str, data: dict[str, Any]) -> str:
    """把工具结果压成一句 Observation（不新增事实）。"""
    if not isinstance(data, dict):
        return str(data)[:200]
    if not data.get("ok"):
        return f"失败：{data.get('error', '未知原因')}"
    if "payable" in data:
        return f"到手 ¥{data['payable']:.2f}（原价 {data['subtotal']:.2f}，优惠 {data['total_discount']:.2f}）"
    if "order" in data:
        o = data["order"]
        return f"订单 {o['order_id']} {o['status']}，实付 {o['total']:.2f}"
    if "products" in data:
        return "；".join(f"{p['name']}({p['sku']}) ¥{p['price']:.2f}" for p in data["products"][:3])
    if "coupons" in data:
        return "可用券：" + "、".join(c["code"] for c in data["coupons"][:4])
    if "eligible" in data:
        return f"退货资格：{'符合' if data['eligible'] else '不符合'}，{data.get('reason', '')}"
    if "content" in data:
        return f"政策：{str(data['content'])[:120]}"
    if "stock" in data:
        return f"库存 {data['stock']} 件"
    return str(data)[:200]


def _run_step(step: PlanStep, tools: dict[str, ToolFn]) -> None:
    fn = tools.get(step.tool)
    if fn is None:
        step.status, step.error = "failed", f"未注册工具 {step.tool}"
        return
    try:
        data = fn(**step.args)
        step.status = "done" if data.get("ok") else "failed"
        step.observation = _summarize(step.tool, data)
        if step.status == "failed":
            step.error = str(data.get("error", ""))
    except Exception as exc:
        step.status, step.error = "failed", f"{type(exc).__name__}: {exc}"


def react_loop(goal: str, tools: dict[str, ToolFn] | None = None,
               max_steps: int = 6) -> PlanResult:
    """显式 ReAct：每一步先写 Thought，再 Action，最后 Observation。

    终止条件：步骤上限 / 无可用动作 / 工具失败 / 重复动作检测。
    """
    started = time.perf_counter()
    tools = tools or default_tools()
    p = plan(goal, strategy="react")
    trace: list[TraceEntry] = []
    seen: set[str] = set()
    terminated_by = "completed"

    for i, step in enumerate(p.steps, 1):
        if i > max_steps:
            terminated_by = "max_steps"
            break
        key = f"{step.tool}:{sorted(step.args.items())}"
        if key in seen:
            terminated_by = "repeated_action"
            break
        seen.add(key)
        trace.append(TraceEntry(index=i, thought=step.description,
                                action=step.tool, args=step.args))
        _run_step(step, tools)
        trace[-1].observation = step.observation or step.error
        if step.status == "failed":
            terminated_by = "tool_failure"
            break

    answer = _final_answer(p)
    return PlanResult(
        goal=goal, strategy="react", plan=p.to_dict(),
        trace=[{"index": t.index, "thought": t.thought, "action": t.action,
                "args": t.args, "observation": t.observation} for t in trace],
        answer=answer, steps_executed=len(trace), terminated_by=terminated_by,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


def plan_and_solve(goal: str, tools: dict[str, ToolFn] | None = None,
                   max_revisions: int = 1) -> PlanResult:
    """Plan-and-Solve：先出完整计划，按依赖顺序执行；失败则重规划一次。"""
    started = time.perf_counter()
    tools = tools or default_tools()
    p = plan(goal, strategy="plan_and_solve")
    trace: list[dict[str, Any]] = []
    terminated_by = "completed"

    for revision in range(max_revisions + 1):
        p.revision = revision
        failed_ids: set[int] = set()
        for step in p.steps:
            if step.status == "done":
                continue
            if any(d in failed_ids for d in step.depends_on):
                step.status = "skipped"
                step.error = "前置步骤失败，跳过"
                trace.append({"index": len(trace) + 1, "thought": step.description,
                              "action": "", "observation": step.error})
                continue
            _run_step(step, tools)
            trace.append({"index": len(trace) + 1, "thought": step.description,
                          "action": step.tool, "args": step.args,
                          "observation": step.observation or step.error})
            if step.status == "failed":
                failed_ids.add(step.id)

        if not failed_ids:
            break
        if revision < max_revisions and len(trace) > len(p.steps):
            # 重规划：把失败步骤降级为更保守的检索，避免死循环
            for step in p.steps:
                if step.status == "failed":
                    step.status = "pending"
                    step.error = ""
                    step.tool = "search_products"
                    step.args = {"keyword": _keyword(goal), "limit": 3}
            terminated_by = "replanned"
        else:
            terminated_by = "tool_failure"
            break

    return PlanResult(
        goal=goal, strategy="plan_and_solve", plan=p.to_dict(), trace=trace,
        answer=_final_answer(p), steps_executed=len(trace),
        terminated_by=terminated_by,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


def _final_answer(p: Plan) -> str:
    done = [s for s in p.steps if s.status == "done" and s.observation]
    if not done:
        return "计划执行后未拿到可用结果，请补充订单号或 SKU 后重试。"
    return "已按计划核实：\n" + "\n".join(f"- {s.description}：{s.observation}" for s in done)
