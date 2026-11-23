"""Supervisor 路由：决定一次提问交给哪个子 Agent。

策略（先模型、后规则、最后默认）：

1. 用 ``LLMClient.structured`` 走结构化输出，拿 ``{agentType, reason, confidence}``；
2. 模型不可用 / 解析失败 / 取值非法 → 退化为关键词打分；
3. 仍无结论 → 默认 ``SHOPPING``（导购是最高频入口）。

**只路由一次**，不做多 Agent 互相调用——避免错误传播与成本爆炸。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.prompts import router_prompt
from app.agents.state import (
    AGENT_OPS,
    AGENT_SERVICE,
    AGENT_SHOPPING,
    AGENT_SUPERVISOR,
    AGENT_TYPES,
)
from app.llm.fallback import LLMClient
from app.llm.router import TaskClass

logger = logging.getLogger(__name__)

# 关键词打分表：命中一次 +1，命中的类别分数最高者胜出
_KEYWORDS: dict[str, tuple[str, ...]] = {
    AGENT_OPS: (
        "销售额", "营收", "gmv", "销量", "卖出", "卖得", "统计", "报表", "环比", "同比",
        "转化率", "客单价", "趋势", "占比", "数据分析", "本月销售", "上个月销售", "多少单",
        "库存周转", "复购", "退款率", "top", "排名",
    ),
    AGENT_SERVICE: (
        "订单", "物流", "快递", "发货", "签收", "派送", "退货", "退款", "售后", "换货",
        "发票", "改地址", "取消订单", "投诉", "保修", "维修", "到哪了", "什么时候到",
        "运费", "无理由", "赔偿",
    ),
    AGENT_SHOPPING: (
        "推荐", "买", "选", "哪个好", "对比", "比较", "便宜", "预算", "型号", "配置",
        "颜色", "尺码", "适合", "好用", "值得", "性价比", "有没有", "找一款", "想入手",
    ),
}


class RouteDecision(BaseModel):
    """结构化路由输出（模型侧 schema）。"""

    agent_type: str = Field(description="SHOPPING / SERVICE / OPS 三选一")
    reason: str = Field(default="", description="不超过 30 字的中文理由")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def _normalize_agent(value: Any) -> str | None:
    """把模型输出归一成合法枚举（容忍大小写与常见同义词）。"""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    aliases = {
        "SHOPPING": AGENT_SHOPPING,
        "GUIDE": AGENT_SHOPPING,
        "PRODUCT": AGENT_SHOPPING,
        "导购": AGENT_SHOPPING,
        "SERVICE": AGENT_SERVICE,
        "AFTERSALE": AGENT_SERVICE,
        "SUPPORT": AGENT_SERVICE,
        "客服": AGENT_SERVICE,
        "OPS": AGENT_OPS,
        "ANALYTICS": AGENT_OPS,
        "OPERATION": AGENT_OPS,
        "运营": AGENT_OPS,
    }
    if text in aliases:
        return aliases[text]
    return text if text in AGENT_TYPES else None


def keyword_route(question: str) -> tuple[str, str]:
    """关键词兜底路由：返回 ``(agentType, reason)``。"""
    text = (question or "").lower()
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for agent, words in _KEYWORDS.items():
        matched = [w for w in words if w and (w in text or w in question)]
        if matched:
            scores[agent] = len(matched)
            hits[agent] = matched
    if not scores:
        return AGENT_SHOPPING, "默认入口：导购"

    # 分数相同优先 SERVICE（售后比导购更依赖准确路由），再 OPS，最后 SHOPPING
    priority = {AGENT_SERVICE: 0, AGENT_OPS: 1, AGENT_SHOPPING: 2}
    best = sorted(scores.items(), key=lambda kv: (-kv[1], priority.get(kv[0], 9)))[0][0]
    reason = "命中关键词：" + "、".join(hits[best][:3])
    return best, reason[:40]


def _history_digest(history: list[dict[str, Any]] | None, limit: int = 4) -> str:
    """把最近几轮压成一行，帮助模型判断"那它呢"这类指代。"""
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = re.sub(r"\s+", " ", str(item.get("content") or ""))[:120]
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines)


async def route(
    question: str,
    history: list[dict[str, Any]] | None = None,
    client: LLMClient | None = None,
) -> tuple[str, str]:
    """决定路由，返回 ``(agentType, reason)``。异常一律降级，绝不抛给上层。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = client or LLMClient()
    messages = [
        SystemMessage(content=router_prompt(_history_digest(history))),
        HumanMessage(content=question),
    ]
    try:
        decision = await llm.structured(messages, RouteDecision, task=TaskClass.ROUTE)
        agent = _normalize_agent(getattr(decision, "agent_type", None))
        if agent and agent != AGENT_SUPERVISOR:
            reason = str(getattr(decision, "reason", "") or "模型路由")[:40]
            logger.info("路由(模型) agent=%s reason=%s", agent, reason)
            return agent, reason
        logger.info("模型路由结果不合法，转入关键词兜底: %r", decision)
    except Exception as exc:  # noqa: BLE001 - 路由失败不能影响主流程
        logger.info("模型路由不可用，转入关键词兜底: %s", exc)

    agent, reason = keyword_route(question)
    logger.info("路由(关键词) agent=%s reason=%s", agent, reason)
    return agent, reason


def allowed_tools(agent_type: str) -> list[str]:
    """该 Agent 可用的工具名（委托给注册表，避免两处维护）。"""
    from app.tools.registry import AGENT_TOOL_NAMES

    return list(AGENT_TOOL_NAMES.get(agent_type.upper(), []))


__all__ = ["RouteDecision", "allowed_tools", "keyword_route", "route"]
