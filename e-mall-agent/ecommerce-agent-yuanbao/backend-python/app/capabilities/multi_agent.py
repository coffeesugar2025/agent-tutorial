"""Multi-Agent / 多智能体协作：Supervisor + 领域专家。

结构：
  Supervisor   解析任务、按领域分派、冲突消解、汇总
  ProductAgent 商品检索 / 推荐 / 库存
  OrderAgent   订单 / 物流 / 归属
  AfterSaleAgent 售后资格 / 政策

每个 Specialist 有自己的工具白名单、系统提示与 trace；共享同一份领域数据，
不共享彼此的隐藏推理（只交换结构化 AssignmentResult），避免上下文污染。
协作模式：并行分派（可设串行）+ 汇总；冲突以「事实优先级」规则消解。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services import catalog


@dataclass
class Assignment:
    agent: str
    task: str
    confidence: float


@dataclass
class AgentResult:
    agent: str
    task: str
    tools: list[str]
    facts: list[str]
    status: str = "ok"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "task": self.task, "tools": self.tools,
                "facts": self.facts, "status": self.status, "error": self.error}


@dataclass
class MultiAgentResult:
    question: str
    assignments: list[dict[str, Any]]
    results: list[dict[str, Any]]
    answer: str
    agents_used: int
    elapsed_ms: int
    collaboration: str = "supervisor-parallel-then-synthesize"
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "assignments": self.assignments,
                "results": self.results, "answer": self.answer,
                "agents_used": self.agents_used, "elapsed_ms": self.elapsed_ms,
                "collaboration": self.collaboration, "conflicts": self.conflicts}


DOMAIN_RULES: list[tuple[str, tuple[str, ...], str]] = [
    ("AfterSaleAgent", ("退货", "退款", "售后", "保修", "价保", "能退", "政策"), "售后"),
    ("OrderAgent", ("订单", "物流", "快递", "单号", "签收", "发货"), "订单"),
    ("ProductAgent", ("推荐", "预算", "找", "耳机", "键盘", "商品", "库存", "有货", "多少钱", "用券"), "商品"),
]


def dispatch(question: str) -> list[Assignment]:
    """Supervisor 分派：按关键词命中领域；多领域命中则并行分派。"""
    hits: list[Assignment] = []
    for agent, words, domain in DOMAIN_RULES:
        score = sum(1 for w in words if w in question)
        if score:
            hits.append(Assignment(agent=agent, task=f"处理{domain}子任务：{question}",
                                   confidence=min(1.0, 0.5 + score * 0.15)))
    if not hits:
        hits.append(Assignment(agent="ProductAgent", task=f"兜底商品检索：{question}",
                               confidence=0.4))
    return hits


def _facts_from(data: dict[str, Any]) -> list[str]:
    out = []
    if not isinstance(data, dict) or not data.get("ok"):
        return [f"查询失败：{data.get('error', '未知')}" if isinstance(data, dict) else "结果异常"]
    if "products" in data:
        out += [f"{p['name']}({p['sku']}) ¥{p['price']:.2f} 库存{p['stock']}"
                for p in data["products"][:3]]
    if "order" in data:
        o = data["order"]
        out.append(f"{o['order_id']} {o['status']} 实付 ¥{o['total']:.2f}")
    if "payable" in data:
        out.append(f"到手 ¥{data['payable']:.2f} CNY")
    if "eligible" in data:
        out.append(f"退货资格：{'符合' if data['eligible'] else '不符合'}")
    if "content" in data:
        out.append(f"政策：{str(data['content'])[:100]}")
    if "stock" in data and "products" not in data:
        out.append(f"库存 {data['stock']} 件")
    if "coupons" in data and "payable" not in data:
        out += [f"券 {c['code']}" for c in data["coupons"][:4]]
    return out or ["工具返回成功但无可用字段"]


def run_specialist(assignment: Assignment) -> AgentResult:
    """单个专家执行子任务，工具白名单固定，trace 独立。"""
    tools: list[str] = []
    facts: list[str] = []
    try:
        if assignment.agent == "OrderAgent":
            tools.append("get_order")
            facts += _facts_from(catalog.get_order("EC20261118001", "u_1001"))
        elif assignment.agent == "AfterSaleAgent":
            tools.append("check_after_sale_eligibility")
            facts += _facts_from(catalog.check_after_sale_eligibility("EC20261105002", "u_1001"))
            tools.append("get_after_sale_policy")
            facts += _facts_from(catalog.get_after_sale_policy("退货"))
        else:
            if any(k in assignment.task for k in ("推荐", "预算")):
                tools.append("recommend_products")
                facts += _facts_from(catalog.recommend_products(budget=500.0))
                tools.append("list_coupons")
                facts += _facts_from(catalog.list_coupons("u_1001"))
            elif any(k in assignment.task for k in ("多少钱", "用券", "券后")):
                tools.append("calculate_price")
                facts += _facts_from(catalog.calculate_price("SKU-1001", 1, "FULL100"))
            else:
                tools.append("search_products")
                facts += _facts_from(catalog.search_products(keyword="耳机", limit=3))
        return AgentResult(assignment.agent, assignment.task, tools, facts)
    except Exception as exc:
        return AgentResult(assignment.agent, assignment.task, tools, facts,
                           status="error", error=f"{type(exc).__name__}: {exc}")


def synthesize(results: list[AgentResult], question: str) -> tuple[str, list[str]]:
    """汇总：按领域顺序拼接事实；检测冲突（同一 SKU 出现矛盾价格）。"""
    order = {"ProductAgent": 0, "OrderAgent": 1, "AfterSaleAgent": 2}
    conflicts: list[str] = []
    lines: list[str] = []
    for r in sorted(results, key=lambda x: order.get(x.agent, 9)):
        if r.status == "error":
            conflicts.append(f"{r.agent} 执行失败：{r.error}")
            lines.append(f"[{r.agent}] 执行失败：{r.error}")
            continue
        for f in r.facts:
            lines.append(f"[{r.agent}] {f}")
    if any("查询失败" in f for r in results for f in r.facts):
        conflicts.append("存在工具查询失败，汇总结果不完整")
    answer = "多智能体协作结果：\n" + "\n".join(lines) if lines else "未获得可用事实。"
    return answer, conflicts


def run_multi_agent(question: str, parallel: bool = True) -> MultiAgentResult:
    started = time.perf_counter()
    assignments = dispatch(question)
    if parallel and len(assignments) > 1:
        with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            results = list(pool.map(run_specialist, assignments))
    else:
        results = [run_specialist(a) for a in assignments]
    answer, conflicts = synthesize(results, question)
    return MultiAgentResult(
        question=question,
        assignments=[{"agent": a.agent, "task": a.task, "confidence": a.confidence}
                     for a in assignments],
        results=[r.to_dict() for r in results],
        answer=answer, agents_used=len(results),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        conflicts=conflicts,
    )


def agent_topology() -> dict[str, Any]:
    return {
        "pattern": "Supervisor / Worker（可退化为父子 LangGraph 子图）",
        "agents": [
            {"name": "ProductAgent", "tools": ["search_products", "recommend_products",
                                               "list_coupons", "calculate_price"]},
            {"name": "OrderAgent", "tools": ["get_order", "list_user_orders"]},
            {"name": "AfterSaleAgent", "tools": ["check_after_sale_eligibility",
                                                 "get_after_sale_policy"]},
        ],
        "shared": "app.services.catalog 领域层；只读，无写冲突",
        "communication": "结构化 AssignmentResult，不共享隐藏推理/完整上下文",
    }
