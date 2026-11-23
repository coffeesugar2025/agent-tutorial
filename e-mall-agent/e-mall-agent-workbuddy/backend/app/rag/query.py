"""查询理解与改写（RAG 入口层）。

提供四种纯本地、确定性的查询改写策略，全部支持注入 ``generator`` 函数，
便于在没有真实 LLM 的环境下测试：

- ``MultiQueryGenerator``：同义词替换 + 多角度模板，扩展为多条查询。
- ``HyDEGenerator``：生成"假设答案文档"，用于以文搜文。
- ``StepBackRewriter``：把细节问题抽象为上位（step-back）问题。
- ``QueryDecomposer``：把复合问题拆成可独立检索的子问题。
"""
from __future__ import annotations

import re
from typing import Callable

# 注入函数的签名：接收查询，返回改写结果。
MultiQueryFn = Callable[[str, int], list[str]]
HyDEFn = Callable[[str], str]
StepBackFn = Callable[[str], str]
DecomposeFn = Callable[[str], list[str]]

# 规则同义词表（电商客服场景）。命中时替换出更口语/更书面的说法。
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "退货": ("退换货", "退回", "退款退货"),
    "退款": ("退回款项", "退钱", "返款"),
    "配送": ("送货", "发货", "物流"),
    "包邮": ("免运费", "满额免邮"),
    "运费": ("邮费", "配送费"),
    "价格": ("售价", "多少钱", "价钱"),
    "保修": ("质保", "维修保障"),
    "优惠": ("折扣", "促销活动"),
    "发票": ("开票", "报销凭证"),
}

# 多角度改写模板：保留原查询语义，但切换问法以召回不同表述的文档。
_ANGLE_TEMPLATES: tuple[str, ...] = (
    "关于「{q}」的规定是什么？",
    "{q}应该如何办理？",
    "请介绍「{q}」的具体规则。",
)

# step-back 主题词 -> 上位问题主题。
_TOPIC_HINTS: tuple[tuple[str, str], ...] = (
    ("退货", "售后服务与退换货政策"),
    ("退款", "退款流程与到账时间规则"),
    ("配送", "物流配送时效规则"),
    ("包邮", "运费与包邮门槛规则"),
    ("运费", "运费收取标准"),
    ("发票", "发票开具规则"),
    ("优惠", "优惠券与促销使用规则"),
    ("保修", "质保与售后保修规则"),
    ("耳机", "数码商品选购要点"),
    ("椅", "办公家具选购要点"),
)

_CONNECTORS = re.compile(r"\s*(?:[，,；;、]|同时|并且|以及|另外|分别)\s*")
_INTERROGATIVE = ("什么", "如何", "怎么", "多少", "是否", "哪", "吗", "为什么")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _default_multiquery(query: str, n: int) -> list[str]:
    """默认改写：原查询 + 同义替换 + 角度模板，保序去重后截取前 n 条。"""
    variants: list[str] = [query]
    for word, replacements in _SYNONYMS.items():
        if word in query:
            for replacement in replacements:
                variants.append(query.replace(word, replacement))
    for template in _ANGLE_TEMPLATES:
        variants.append(template.format(q=query))
    return _dedupe(variants)[:max(1, n)]


class MultiQueryGenerator:
    """把单条查询改写为多条语义相近、角度不同的查询。"""

    def __init__(self, n: int = 3, generator: MultiQueryFn | None = None) -> None:
        if n < 1:
            raise ValueError("n 必须 >= 1")
        self.n = n
        self.generator = generator or _default_multiquery

    def generate(self, query: str, n: int | None = None) -> list[str]:
        """返回改写后的查询列表（至少包含原查询，顺序确定）。"""
        results = self.generator(query, n or self.n)
        cleaned = _dedupe(list(results))
        return cleaned or [query]


def _default_hyde(query: str) -> str:
    """默认假设答案文档：一段包含查询关键词的说明性文字。"""
    return (
        f"关于「{query}」的说明：{query}通常涉及适用范围、办理条件与具体时限，"
        "用户需要结合自身情况参考官方条款，按规定流程办理即可。"
    )


class HyDEGenerator:
    """生成"假设答案文档"（Hypothetical Document Embeddings）。"""

    def __init__(self, generator: HyDEFn | None = None) -> None:
        self.generator = generator or _default_hyde

    def generate(self, query: str) -> str:
        """返回一段假设性答案文本（本地 stub 或注入函数输出）。"""
        return str(self.generator(query)).strip()


def _default_step_back(query: str) -> str:
    """默认上位问题：命中主题词则抽象为该类问题的通用问法。"""
    for word, topic in _TOPIC_HINTS:
        if word in query:
            return f"关于{topic}，一般的规定和核心要点是什么？"
    return f"「{query}」这一类问题的通用原则与判断依据是什么？"


class StepBackRewriter:
    """把细节问题抽象成上位（step-back）问题，提高召回广度。"""

    def __init__(self, generator: StepBackFn | None = None) -> None:
        self.generator = generator or _default_step_back

    def rewrite(self, query: str) -> str:
        """返回抽象化后的问题。"""
        return str(self.generator(query)).strip() or query


def _normalize_subquestion(part: str) -> str:
    text = part.strip().rstrip("？?。!！")
    if not text:
        return ""
    if any(word in text for word in _INTERROGATIVE):
        return text + "？"
    return f"{text}是什么？"


def _default_decompose(query: str) -> list[str]:
    """默认拆分：先处理"……分别……"，再按连接词切分，最后处理"A和B的区别"。"""
    if "分别" in query:
        head, _, tail = query.partition("分别")
        topics = [p for p in re.split(r"\s*(?:和|与|、|,|，)\s*", head) if p.strip()]
        if len(topics) > 1:
            return _dedupe(_normalize_subquestion(t + tail) for t in topics)
    parts = [p for p in _CONNECTORS.split(query) if p.strip()]
    if len(parts) > 1:
        return _dedupe(_normalize_subquestion(p) for p in parts)
    if "区别" in query and "和" in query:
        left, right = query.split("和", 1)
        return _dedupe([
            _normalize_subquestion(left),
            _normalize_subquestion(right),
            query.strip(),
        ])
    return [query]


class QueryDecomposer:
    """把复合问题拆成可独立检索的子问题。"""

    def __init__(self, generator: DecomposeFn | None = None) -> None:
        self.generator = generator or _default_decompose

    def decompose(self, query: str) -> list[str]:
        """返回子问题列表；无法拆分时原样返回单元素列表。"""
        results = self.generator(query)
        return _dedupe(list(results)) or [query]


__all__ = [
    "MultiQueryGenerator", "HyDEGenerator", "StepBackRewriter", "QueryDecomposer",
    "MultiQueryFn", "HyDEFn", "StepBackFn", "DecomposeFn",
]
