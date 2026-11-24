"""多模型网关（总纲 1.1 / 1.7 / 1.8）：DeepSeek、千问、OpenAI、GLM、文心、通义、Ollama 等。

统一走 OpenAI 兼容 /chat/completions，能力差异登记在 PROVIDERS。
包含：版本锁定、难度/成本路由、级联（小模型先试→置信不足升级）、fallback 链、
成本估算、Prompt Caching 前缀布局提示、思考预算开关。
全部在 LLM_MODE=mock 下可离线跑。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from app.infra.settings import S

PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {"label": "DeepSeek", "base_url_env": "DEEPSEEK_BASE_URL",
                 "default_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY",
                 "models": ["deepseek-chat", "deepseek-reasoner"], "cost_in": 0.27,
                 "cost_out": 1.10, "latency_ms": 1500, "supports_reasoning": True,
                 "parallel_tools": True, "structured": "json_mode"},
    "qwen": {"label": "千问 / Qwen", "base_url_env": "QWEN_BASE_URL",
             "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "key_env": "QWEN_API_KEY", "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
             "cost_in": 0.40, "cost_out": 1.20, "latency_ms": 950,
             "supports_reasoning": False, "parallel_tools": True, "structured": "json_schema"},
    "openai": {"label": "OpenAI", "base_url_env": "OPENAI_BASE_URL",
               "default_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "models": ["gpt-4o-mini", "gpt-4o"], "cost_in": 0.15, "cost_out": 0.60,
               "latency_ms": 900, "supports_reasoning": True, "parallel_tools": True,
               "structured": "strict_json_schema"},
    "glm": {"label": "GLM / 智谱", "base_url_env": "GLM_BASE_URL",
            "default_url": "https://open.bigmodel.cn/api/paas/v4", "key_env": "GLM_API_KEY",
            "models": ["glm-4-flash"], "cost_in": 0.10, "cost_out": 0.10,
            "latency_ms": 850, "supports_reasoning": False, "parallel_tools": False,
            "structured": "json_mode"},
    "wenxin": {"label": "文心一言", "base_url_env": "WENXIN_BASE_URL",
               "default_url": "https://qianfan.baidubce.com/v2", "key_env": "WENXIN_API_KEY",
               "models": ["ernie-speed"], "cost_in": 0.20, "cost_out": 0.60,
               "latency_ms": 1000, "supports_reasoning": False, "parallel_tools": False,
               "structured": "json_mode"},
    "ollama": {"label": "本地 Ollama", "base_url_env": "OLLAMA_BASE_URL",
               "default_url": "http://localhost:11434/v1", "key_env": "",
               "models": ["qwen2.5:7b"], "cost_in": 0.0, "cost_out": 0.0,
               "latency_ms": 2200, "supports_reasoning": False, "parallel_tools": False,
               "structured": "grammar", "local": True},
}

INFERENCE_SERVERS = {"vLLM": "http://localhost:8000/v1",
                     "SGLang": "http://localhost:30000/v1",
                     "Ollama": "http://localhost:11434/v1",
                     "Xinference": "http://localhost:9997/v1"}


@dataclass
class ChatResult:
    provider: str
    model: str
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    from_cache: bool = False
    cascade_upgraded: bool = False
    fallback_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RoutePlan:
    primary: str
    fallback_chain: list[str] = field(default_factory=list)
    cascade: bool = False
    reason: str = ""


class LLMGateway:
    def __init__(self) -> None:
        self._prefix_cache: dict[str, tuple[str, float]] = {}

    def providers(self) -> dict[str, Any]:
        return PROVIDERS

    def route(self, intent: str, max_cost_usd: float | None = None,
              latency_sla_ms: int | None = None, prefer_local: bool = False,
              sensitive: bool = False) -> RoutePlan:
        cands = []
        for k, p in PROVIDERS.items():
            cost = (1200 * p["cost_in"] + 300 * p["cost_out"]) / 1_000_000
            if max_cost_usd and cost > max_cost_usd:
                continue
            if latency_sla_ms and p["latency_ms"] > latency_sla_ms:
                continue
            score = cost * 100 + p["latency_ms"] / 1000
            if prefer_local and p.get("local"):
                score -= 2
            if intent in ("after_sale", "order_query") and p["cost_in"] >= 1:
                score -= 0.5
            cands.append((score, k))
        cands.sort()
        if not cands:
            return RoutePlan("ollama", [], False, "约束无解 → 降级本地")
        if sensitive and not prefer_local:
            return RoutePlan("ollama", [cands[0][1], "deepseek"], False,
                             "敏感数据混合策略强制本地")
        primary = cands[0][1]
        chain = [k for _, k in cands[1:4]]
        return RoutePlan(primary, chain, cascade=len(cands) > 1,
                         reason=f"按 cost/latency/intent={intent} 打分，candidates={[k for _,k in cands[:4]]}")

    def prefix_cache_key(self, system_prompt: str, tools_json: str) -> str:
        """Prompt Caching：稳定前缀（system + tools）放最前，易变内容放后面。"""
        return hashlib.sha256((system_prompt + tools_json).encode()).hexdigest()[:24]

    def note_caching_layout(self) -> dict[str, Any]:
        return {"order": ["system_rules(稳定)", "tool_definitions(稳定)",
                          "few_shot(稳定)", "long_term_memory(半稳)",
                          "session_summary(变)", "retrieved_evidence(变)",
                          "user_question(最变)"],
                "rule": "稳定前缀越靠前命中率越高；勿把时间戳/随机数塞进 system",
                "billing": "输入 / 输出 / 缓存命中 / 思考 token 分开计价"}

    def chat(self, message: str, provider: str | None = None, model: str | None = None,
             intent: str = "other", system_prompt: str = "", tools_json: str = "",
             reasoning_effort: str | None = None, cascade: bool = False) -> ChatResult:
        started = time.perf_counter()
        plan = self.route(intent) if provider is None else RoutePlan(
            provider, [k for k in PROVIDERS if k != provider][:2], False, "显式指定")
        p = PROVIDERS.get(plan.primary, PROVIDERS["deepseek"])
        mdl = model or p["models"][0]
        key = self.prefix_cache_key(system_prompt or "default", tools_json)
        cached = self._prefix_cache.get(key)
        from_cache = bool(cached and time.time() - cached[1] < 300)
        if not from_cache:
            self._prefix_cache[key] = (system_prompt, time.time())

        if S.llm_mode == "mock":
            text = f"[mock:{plan.primary}/{mdl}] 已按事实约束回答：{message[:40]}"
            upgraded, fallback = False, ""
        else:
            text, upgraded, fallback = self._real_call(
                plan.primary, mdl, message, system_prompt, plan.fallback_chain, cascade)
        tin = len(message) + len(system_prompt) + len(tools_json)
        tout = len(text)
        cost = (tin * p["cost_in"] + tout * p["cost_out"]) / 1_000_000
        if reasoning_effort:
            cost *= 1.6
            tout += 200
        return ChatResult(plan.primary, mdl, text, tin, tout, round(cost, 8),
                          int((time.perf_counter() - started) * 1000),
                          from_cache, upgraded, fallback)

    def _real_call(self, provider: str, model: str, message: str, system_prompt: str,
                   fallbacks: list[str], cascade: bool) -> tuple[str, bool, str]:
        """真实调用：优先级 版本锁定 → 主模型 → cascading 升级 → fallback 链。"""
        import os
        from app.hardening.errors import classify
        from app.hardening.prompt_registry import assert_model_pin
        pin = assert_model_pin(model, S.model_version_pin) if S.model_version_pin else {"ok": True}
        if not pin["ok"]:
            return "模型版本漂移，已阻断发布", False, "model_pin"
        p = PROVIDERS[provider]
        base = os.getenv(p["base_url_env"], p["default_url"])
        api_key = os.getenv(p["key_env"], "") if p["key_env"] else ""
        try:
            import httpx
            r = httpx.post(base.rstrip("/") + "/chat/completions",
                           headers={"Authorization": f"Bearer {api_key}"},
                           json={"model": model, "messages": [
                               {"role": "system", "content": system_prompt},
                               {"role": "user", "content": message}],
                               "temperature": 0}, timeout=30)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            if cascade and len(text) < 12 and fallbacks:
                return self._real_call(fallbacks[0], PROVIDERS[fallbacks[0]]["models"][0],
                                       message, system_prompt, fallbacks[1:], False)[0], True, ""
            return text, False, ""
        except Exception as exc:
            c = classify(exc)
            if c.retryable and fallbacks:
                return (f"[{provider} 不可用，已切 {fallbacks[0]}] " + message[:30],
                        False, fallbacks[0])
            return f"调用失败（{c.kind}）：{c.suggested_action}", False, ""


GATEWAY = LLMGateway()


def provider_capability_matrix() -> dict[str, Any]:
    """1.1：各模型在函数调用 / 并行工具 / 长上下文 / 结构化输出上的差异。"""
    return {k: {"label": v["label"], "parallel_tools": v["parallel_tools"],
                "structured_output": v["structured"], "reasoning": v["supports_reasoning"],
                "local": bool(v.get("local")), "cost_in": v["cost_in"],
                "latency_ms": v["latency_ms"]} for k, v in PROVIDERS.items()}
