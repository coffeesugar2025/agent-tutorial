"""LLM 与模型工程：模型/API、路由、成本延迟、部署、训练任务契约。

诚实边界：SFT / LoRA / QLoRA / DPO / RLHF / 量化 / 剪枝 / 蒸馏属于「模型训练与
推理基础设施」，不是在电商 Agent 应用仓库里能执行的代码（需要 GPU、数据集、
训练框架与独立服务）。本模块提供的是应用侧真实可落地的三件事：
  1) Provider / 推理服务器注册表（9 家模型 + 4 种本地推理服务，全部 OpenAI 兼容 base_url）
  2) ModelRouter（按意图 / 成本上限 / 延迟 SLA / 本地优先做选择）与成本延迟估算
  3) TrainingJobSpec（训练任务的标准化契约、数据集格式、评测钩子、状态机），
     明确标注「提交到外部训练平台执行，本仓库不训练」

vLLM / Ollama / SGLang / Xinference 通过 OpenAI 兼容端点直接接入 build_model() 的
OPENAI_BASE_URL，属于真实可用能力，不是占位注释。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.capabilities.observability import METRICS

# 成本为「量级示意值」，用于路由比较，不是厂商报价；生产从计费 API 拉取。
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {"label": "OpenAI", "api_style": "openai", "base_url_env": "OPENAI_BASE_URL",
               "models": ["gpt-4o-mini", "gpt-4o"], "cost_in": 0.15, "cost_out": 0.60,
               "latency_ms": 900, "deployment": "cloud"},
    "anthropic": {"label": "Claude / Anthropic", "api_style": "openai-compatible",
                  "base_url_env": "ANTHROPIC_BASE_URL", "models": ["claude-sonnet-4"],
                  "cost_in": 3.0, "cost_out": 15.0, "latency_ms": 1200, "deployment": "cloud"},
    "gemini": {"label": "Gemini", "api_style": "openai-compatible",
               "base_url_env": "GEMINI_BASE_URL", "models": ["gemini-2.0-flash"],
               "cost_in": 0.10, "cost_out": 0.40, "latency_ms": 800, "deployment": "cloud"},
    "deepseek": {"label": "DeepSeek", "api_style": "openai",
                 "base_url_env": "DEEPSEEK_BASE_URL", "models": ["deepseek-chat"],
                 "cost_in": 0.27, "cost_out": 1.10, "latency_ms": 1500, "deployment": "cloud"},
    "qwen": {"label": "Qwen / 通义千问", "api_style": "openai-compatible",
             "base_url_env": "QWEN_BASE_URL", "models": ["qwen-plus", "qwen-turbo"],
             "cost_in": 0.40, "cost_out": 1.20, "latency_ms": 950, "deployment": "cloud"},
    "llama": {"label": "Llama (本地/自建)", "api_style": "openai-compatible",
              "base_url_env": "LLAMA_BASE_URL", "models": ["llama-3.1-8b"],
              "cost_in": 0.0, "cost_out": 0.0, "latency_ms": 2200, "deployment": "local"},
    "glm": {"label": "GLM / 智谱", "api_style": "openai-compatible",
            "base_url_env": "GLM_BASE_URL", "models": ["glm-4-flash"],
            "cost_in": 0.10, "cost_out": 0.10, "latency_ms": 850, "deployment": "cloud"},
    "wenxin": {"label": "文心一言", "api_style": "openai-compatible",
               "base_url_env": "WENXIN_BASE_URL", "models": ["ernie-speed"],
               "cost_in": 0.20, "cost_out": 0.60, "latency_ms": 1000, "deployment": "cloud"},
    "tongyi": {"label": "通义 (独立端点)", "api_style": "openai-compatible",
               "base_url_env": "TONGYI_BASE_URL", "models": ["qwen-max"],
               "cost_in": 1.6, "cost_out": 6.4, "latency_ms": 1100, "deployment": "cloud"},
}

INFERENCE_SERVERS: dict[str, dict[str, str]] = {
    "vLLM": {"base_url": "http://localhost:8000/v1", "note": "OpenAI 兼容 server，直接设 OPENAI_BASE_URL"},
    "Ollama": {"base_url": "http://localhost:11434/v1", "note": "ollama serve 的 OpenAI 兼容层"},
    "SGLang": {"base_url": "http://localhost:30000/v1", "note": "OpenAI 兼容 runtime"},
    "Xinference": {"base_url": "http://localhost:9997/v1", "note": "OpenAI 兼容 RESTful 端点"},
}

EVAL_METRICS = ["任务成功率", "工具调用准确率", "幻觉率", "Token 成本",
                "推理耗时 P95/P99", "回答准确性", "端到端完成质量"]


@dataclass
class RouteDecision:
    provider: str
    model: str
    reason: str
    estimated_cost_usd: float
    estimated_latency_ms: int
    deployment: str
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "reason": self.reason,
                "estimated_cost_usd": self.estimated_cost_usd,
                "estimated_latency_ms": self.estimated_latency_ms,
                "deployment": self.deployment, "alternatives": self.alternatives}


class CostEstimator:
    @staticmethod
    def estimate(provider: str, tokens_in: int, tokens_out: int) -> dict[str, Any]:
        p = PROVIDERS.get(provider)
        if not p:
            raise KeyError(f"未知 provider：{provider}")
        cost = (tokens_in * p["cost_in"] + tokens_out * p["cost_out"]) / 1_000_000
        METRICS.inc("llm_tokens_in", tokens_in, provider=provider)
        METRICS.inc("llm_tokens_out", tokens_out, provider=provider)
        METRICS.observe("llm_cost_usd", cost)
        return {"provider": provider, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": round(cost, 8), "unit": "USD / 示意单价"}


class ModelRouter:
    """按硬约束过滤 + 打分：成本、延迟、本地优先、意图强度。"""

    def __init__(self, providers: dict[str, dict[str, Any]] | None = None) -> None:
        self.providers = providers or PROVIDERS

    def route(self, intent: str = "other", tokens_in: int = 1200,
              tokens_out: int = 300, max_cost_usd: float | None = None,
              latency_sla_ms: int | None = None, prefer_local: bool = False,
              require_strong: bool = False) -> RouteDecision:
        strong = {"after_sale", "order_query", "complaint"}
        candidates: list[dict[str, Any]] = []
        for key, p in self.providers.items():
            cost = (tokens_in * p["cost_in"] + tokens_out * p["cost_out"]) / 1_000_000
            lat = p["latency_ms"]
            if max_cost_usd is not None and cost > max_cost_usd:
                continue
            if latency_sla_ms is not None and lat > latency_sla_ms:
                continue
            if require_strong and p["cost_in"] < 1.0 and p["deployment"] == "cloud":
                continue
            score = cost * 100 + lat / 1000.0
            if prefer_local and p["deployment"] == "local":
                score -= 2.0
            if intent in strong and p["cost_in"] >= 1.0:
                score -= 0.5
            candidates.append({"provider": key, "model": p["models"][0], "score": round(score, 4),
                               "cost_usd": round(cost, 8), "latency_ms": lat,
                               "deployment": p["deployment"]})
        if not candidates:
            # 无候选时降级到最便宜的可用模型，并如实标注约束未满足
            cheapest = min(self.providers.items(), key=lambda kv: kv[1]["cost_in"])
            key, p = cheapest
            cost = (tokens_in * p["cost_in"] + tokens_out * p["cost_out"]) / 1_000_000
            return RouteDecision(key, p["models"][0], "约束无解，降级到最低价模型",
                                 round(cost, 8), p["latency_ms"], p["deployment"])
        candidates.sort(key=lambda c: c["score"])
        best = candidates[0]
        return RouteDecision(
            best["provider"], best["model"],
            f"按 cost/latency/intent={intent}/prefer_local={prefer_local} 打分最优",
            best["cost_usd"], best["latency_ms"], best["deployment"],
            [{"provider": c["provider"], "score": c["score"]} for c in candidates[1:4]],
        )


ROUTER = ModelRouter()


class DeploymentPolicy:
    """本地 / 云端 / 混合三态；数据敏感意图强制本地。"""

    SENSITIVE = {"order_query", "after_sale", "pii"}

    @staticmethod
    def decide(intent: str, mode: str = "hybrid") -> dict[str, Any]:
        if mode not in ("local", "cloud", "hybrid"):
            raise ValueError("mode 必须是 local / cloud / hybrid")
        if mode == "hybrid" and intent in DeploymentPolicy.SENSITIVE:
            chosen, reason = "local", f"意图 {intent} 含用户数据，混合策略强制本地"
        else:
            chosen, reason = mode, f"按部署模式 {mode}"
        return {"mode": mode, "chosen": chosen, "reason": reason,
                "base_url_hint": INFERENCE_SERVERS["Ollama"]["base_url"]
                if chosen == "local" else "${OPENAI_BASE_URL}"}


def structured_output_validate(payload: Any, schema: Any) -> dict[str, Any]:
    """JSON Mode / 结构化输出的应用侧兜底校验：解析 → Pydantic 校验 → 明确错误。"""
    import json
    from pydantic import ValidationError

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            return {"ok": False, "stage": "json_parse", "error": str(exc)}
    try:
        obj = schema.model_validate(payload)
    except ValidationError as exc:
        return {"ok": False, "stage": "schema_validate",
                "error": exc.errors(include_url=False)[:3]}
    except Exception as exc:
        return {"ok": False, "stage": "schema_validate",
                "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "data": obj.model_dump(mode="json")}


# ---------------------------------------------------------------- 训练任务契约
TRAINING_METHODS = ("SFT", "LoRA", "QLoRA", "DPO", "RLHF",
                    "quantize", "prune", "distill")


@dataclass
class TrainingJobSpec:
    """模型训练任务的标准化契约。本仓库只生成/校验 spec，不执行训练。"""

    method: str
    base_model: str
    dataset_ref: str
    output_name: str
    hyperparams: dict[str, Any] = field(default_factory=dict)
    eval_hook: str = "app.capabilities.observability.SUITE"
    status: str = "submitted"          # submitted / queued / running / succeeded / failed
    submitted_at: float = field(default_factory=time.time)
    executed_here: bool = False         # 永远 False：训练在外部平台执行

    def validate(self) -> dict[str, Any]:
        errors = []
        if self.method not in TRAINING_METHODS:
            errors.append(f"未知训练方法：{self.method}")
        if not self.base_model or not self.dataset_ref:
            errors.append("base_model 与 dataset_ref 必填")
        if self.executed_here:
            errors.append("应用仓库禁止执行训练任务")
        return {"ok": not errors, "errors": errors,
                "note": "spec 提交到外部训练平台（需 GPU / 数据集 / 训练框架）"}

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "base_model": self.base_model,
                "dataset_ref": self.dataset_ref, "output_name": self.output_name,
                "hyperparams": self.hyperparams, "eval_hook": self.eval_hook,
                "status": self.status, "executed_here": self.executed_here,
                "validation": self.validate()}


DATASET_CONTRACT = {
    "sft": {"format": "jsonl", "fields": ["instruction", "input", "output"]},
    "dpo": {"format": "jsonl", "fields": ["prompt", "chosen", "rejected"]},
    "rlhf": {"format": "jsonl", "fields": ["prompt", "response", "reward"]},
    "eval": {"format": "jsonl", "fields": ["case_id", "question", "expected_tools", "expected_answer_contains"]},
}


def model_eng_spec() -> dict[str, Any]:
    return {
        "providers": sorted(PROVIDERS),
        "inference_servers": {k: v["base_url"] for k, v in INFERENCE_SERVERS.items()},
        "application_capabilities": ["init_chat_model(provider:model)", "response_format / JSON Mode 校验",
                                     "ModelRouter", "CostEstimator", "DeploymentPolicy(local/cloud/hybrid)",
                                     "temperature=0 可复现", "兼容网关 BASE_URL 透传"],
        "training_methods_contract": list(TRAINING_METHODS),
        "training_boundary": "仅提供 TrainingJobSpec / 数据集契约 / 评测钩子；训练在外部平台执行，本仓库不含训练代码",
        "eval_metrics": EVAL_METRICS,
    }
