"""查询理解（总纲 4.6）：召回质量的上游。之前项目拿原始 question 直接召回，全缺这块。

  rewrite            口语归一 / 纠错
  decompose          复杂问题拆子查询
  multi_query        多路改写扩展
  hyde               假设性文档嵌入（生成式，离线用模板近似）
  should_retrieve    何时不该检索（闲聊 / 已有上下文 / 模型已知）
"""
from __future__ import annotations

import re
from typing import Any

NORMALIZE = {"多少钱": "价格", "到手": "到手价", "能退不": "退货资格",
             "快递到哪": "物流状态", "单号": "订单号", "咋样": "评价"}
CHITCHAT = ("你好", "在吗", "谢谢", "你是谁", "拜拜", "hi", "hello")
NO_RETRIEVAL = ("刚才说的", "上面那个", "继续", "再说一遍")


def rewrite(q: str) -> str:
    s = q.strip()
    for a, b in NORMALIZE.items():
        s = s.replace(a, b)
    s = re.sub(r"[\s，,。!！?？]+", " ", s).strip()
    return s


def should_retrieve(q: str, has_history: bool = False) -> dict[str, Any]:
    low = q.strip().lower()
    if any(c in low for c in CHITCHAT):
        return {"retrieve": False, "reason": "闲聊"}
    if has_history and any(c in q for c in NO_RETRIEVAL):
        return {"retrieve": False, "reason": "上下文已覆盖，直接续答省一次检索"}
    if len(q) < 3:
        return {"retrieve": False, "reason": "信息量不足，先澄清"}
    return {"retrieve": True, "reason": "需要外部事实"}


def decompose(q: str) -> list[str]:
    """复杂问题按「和 / 以及 / 顺便 / 再」拆成子查询。"""
    parts = re.split(r"(?:和|以及|顺便|再|另外|还有|\+|,|，)\s*", q)
    return [p.strip() for p in parts if len(p.strip()) >= 3] or [q]


def multi_query(q: str) -> list[str]:
    base = rewrite(q)
    variants = [base, base.replace("吗", "").replace("？", "").strip()]
    if "政策" in base:
        variants.append(base + " 官方规定")
    if any(k in base for k in ("券", "优惠", "到手")):
        variants.append(base + " 门槛 封顶")
    return list(dict.fromkeys(v for v in variants if v))


def hyde(q: str) -> str:
    """HyDE 假设性文档：离线用模板近似，生产替换为模型生成。"""
    return (f"以下是一段可能回答「{q}」的资料：该问题涉及电商订单、商品、优惠券或售后政策，"
            "答案应给出具体数字、适用条件与官方口径，并标注来源。")


def understand(q: str, has_history: bool = False) -> dict[str, Any]:
    gate = should_retrieve(q, has_history)
    out: dict[str, Any] = {"original": q, "rewritten": rewrite(q), "gate": gate,
                           "sub_queries": decompose(q), "multi_queries": multi_query(q)}
    if gate["retrieve"]:
        out["hyde_document"] = hyde(out["rewritten"])
        out["plan"] = ["rewrite", "decompose", "multi_query", "hyde", "hybrid_retrieve"]
    else:
        out["plan"] = ["skip_retrieval", "answer_from_context"]
    return out
