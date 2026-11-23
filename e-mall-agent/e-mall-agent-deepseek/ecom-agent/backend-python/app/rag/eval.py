"""检索质量评估：recall@k / MRR / nDCG@k。

输入是"检索返回的 id 序列"与"标注的相关 id 集合"，纯函数实现，便于单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def recall_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """召回率：前 k 个结果覆盖了多少相关项。"""
    if not relevant:
        return 0.0
    top = retrieved[:k]
    return len(set(top) & relevant) / len(relevant)


def precision_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    return len(set(top) & relevant) / k


def reciprocal_rank(retrieved: list[int], relevant: set[int]) -> float:
    """第一个相关结果排名的倒数。"""
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(results: list[tuple[list[int], set[int]]]) -> float:
    if not results:
        return 0.0
    return round(sum(reciprocal_rank(retrieved, relevant) for retrieved, relevant in results) / len(results), 4)


def dcg_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """二值相关性 DCG。"""
    total = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        gain = 1.0 if doc_id in relevant else 0.0
        total += gain / math.log2(rank + 1)
    return total


def ndcg_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """归一化 DCG（理想排序为相关项全部排在最前）。"""
    if not relevant or k <= 0:
        return 0.0
    ideal = dcg_at_k(list(relevant)[:k], relevant, k)
    if ideal <= 0:
        return 0.0
    return round(dcg_at_k(retrieved, relevant, k) / ideal, 4)


@dataclass
class RetrievalEvalReport:
    """一次评估的汇总。"""

    cases: int = 0
    recall_at_k: dict[int, float] = field(default_factory=dict)
    ndcg_at_k: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    details: list[dict[str, object]] = field(default_factory=list)


def evaluate_retrieval(
    cases: list[dict[str, object]],
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> RetrievalEvalReport:
    """批量评估。

    ``cases`` 每项形如 ``{"query": "...", "retrieved": [11, 22], "relevant": [22]}``。
    """
    report = RetrievalEvalReport(cases=len(cases))
    if not cases:
        return report
    pairs: list[tuple[list[int], set[int]]] = []
    for case in cases:
        retrieved = [int(x) for x in (case.get("retrieved") or [])]  # type: ignore[union-attr]
        relevant = {int(x) for x in (case.get("relevant") or [])}  # type: ignore[union-attr]
        pairs.append((retrieved, relevant))
        detail: dict[str, object] = {
            "query": case.get("query", ""),
            "retrieved": retrieved,
            "relevant": sorted(relevant),
            "mrr": reciprocal_rank(retrieved, relevant),
        }
        for k in ks:
            detail[f"recall@{k}"] = recall_at_k(retrieved, relevant, k)
            detail[f"ndcg@{k}"] = ndcg_at_k(retrieved, relevant, k)
        report.details.append(detail)

    for k in ks:
        report.recall_at_k[k] = round(
            sum(recall_at_k(retrieved, relevant, k) for retrieved, relevant in pairs) / len(pairs), 4
        )
        report.ndcg_at_k[k] = round(
            sum(ndcg_at_k(retrieved, relevant, k) for retrieved, relevant in pairs) / len(pairs), 4
        )
    report.mrr = mean_reciprocal_rank(pairs)
    return report


def report_to_dict(report: RetrievalEvalReport) -> dict[str, object]:
    """序列化（落 eval_run.report）。"""
    return {
        "cases": report.cases,
        "mrr": report.mrr,
        "recallAtK": {str(k): v for k, v in report.recall_at_k.items()},
        "ndcgAtK": {str(k): v for k, v in report.ndcg_at_k.items()},
        "details": report.details,
    }


__all__ = [
    "RetrievalEvalReport",
    "dcg_at_k",
    "evaluate_retrieval",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "report_to_dict",
]
