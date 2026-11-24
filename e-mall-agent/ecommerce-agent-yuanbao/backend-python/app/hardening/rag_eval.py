"""RAG 分层评估（总纲 4.12 / 7.2 / 7.6）：能定位是「没召回 / 没排上 / 没用对 / 生成错」。

之前只有端到端 quality_score，全缺这些指标。
"""
from __future__ import annotations

import math
from typing import Any


def recall_at_k(relevant: set[str], retrieved: list[str], k: int | None = None) -> float:
    ks = retrieved[:k] if k else retrieved
    return round(len(relevant & set(ks)) / max(1, len(relevant)), 4)


def mrr(relevant: set[str], retrieved: list[str]) -> float:
    for i, d in enumerate(retrieved, 1):
        if d in relevant:
            return round(1.0 / i, 4)
    return 0.0


def ndcg_at_k(relevant: set[str], retrieved: list[str], k: int = 5) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(retrieved[:k], 1) if d in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return round(dcg / max(1e-9, ideal), 4)


def context_precision(relevant: set[str], retrieved: list[str], k: int = 5) -> float:
    return round(len(relevant & set(retrieved[:k])) / max(1, min(k, len(retrieved))), 4)


def context_recall(answer_facts: set[str], passages_text: str) -> float:
    covered = sum(1 for f in answer_facts if f in passages_text)
    return round(covered / max(1, len(answer_facts)), 4)


def layered_diagnose(question: str, relevant: set[str], retrieved: list[str],
                     used_in_answer: list[str], answer: str,
                     passages_text: str, expected_facts: set[str]) -> dict[str, Any]:
    metrics = {
        "retrieval": {"recall@5": recall_at_k(relevant, retrieved, 5),
                      "mrr": mrr(relevant, retrieved), "ndcg@5": ndcg_at_k(relevant, retrieved, 5)},
        "context": {"precision@5": context_precision(relevant, retrieved, 5),
                    "recall": context_recall(expected_facts, passages_text)},
        "generation": {"facts_in_passages": context_recall(expected_facts, passages_text),
                       "used_refs": len(used_in_answer),
                       "faithful": all(f in passages_text for f in expected_facts)},
    }
    r = metrics["retrieval"]["recall@5"]
    p = metrics["context"]["precision@5"]
    if r < 0.5:
        layer, action = "检索没召回到", "改切片/加多路召回/做查询改写，别先调 prompt"
    elif r >= 0.5 and p < 0.5:
        layer, action = "召回了没排上", "加 rerank / 调 RRF 权重 / 阈值截断"
    elif not metrics["generation"]["faithful"]:
        layer, action = "用了但生成错 / 排上了没用对", "强制引用编号 + 事实校验 + 拒答策略"
    else:
        layer, action = "生成侧", "检查答案组织与话术"
    return {"question": question, "metrics": metrics, "bottleneck_layer": layer,
            "recommended_action": action, "order": "先看轨迹 → 再看单步 → 最后看模型"}


def golden_retrieval_set() -> list[dict[str, Any]]:
    return [
        {"question": "退货政策是几天", "relevant": {"doc_policies#policy_return"},
         "expected_facts": {"7 天", "无理由"}},
        {"question": "价保多久", "relevant": {"doc_policies#policy_price"},
         "expected_facts": {"15 天"}},
        {"question": "FULL100 券门槛", "relevant": {"doc_coupons#full100"},
         "expected_facts": {"500", "100"}},
    ]
