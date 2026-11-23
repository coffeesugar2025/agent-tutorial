"""LLM 工程专项测试：推理配置、Token 预算、结构化输出与模型选型 Benchmark。"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.llm.benchmark import ModelProfile, ModelRequirements, select_model
from app.llm.reasoning import (
    ReasoningConfig,
    ReasoningEffort,
    build_reasoning_model_kwargs,
    is_reasoning_model,
)
from app.llm.structured import (
    StructuredOutputSpec,
    constrained_model_kwargs,
    extract_json,
    validate_structured,
)
from app.llm.tokenizer import BudgetSplit, EnhancedTokenCounter, TokenCounter


class Answer(BaseModel):
    """测试用结构化输出模型。"""

    answer: str
    confidence: float = Field(ge=0, le=1)


# --------------------------------------------------------------------------
# 5. 推理模型与 Test-time Compute
# --------------------------------------------------------------------------
class TestReasoning:
    def test_o1_family_uses_reasoning_effort(self):
        """推理模型：o1/R1 类只给 reasoning_effort 与完成预算，不给 temperature。"""
        kwargs = build_reasoning_model_kwargs(
            "openai",
            ReasoningConfig(reasoning_effort=ReasoningEffort.HIGH, max_cot_tokens=4096),
            model="o1-preview",
        )
        assert kwargs["model"] == "o1-preview"
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["max_completion_tokens"] == 4096
        assert "temperature" not in kwargs

        exposed = build_reasoning_model_kwargs("deepseek-r1", model="deepseek-r1",
                                               config=ReasoningConfig(expose_chain_of_thought=True))
        assert exposed["reasoning_effort"] == "medium"
        assert exposed["reasoning_summary"] == "detailed"

    def test_normal_model_uses_temperature_and_prompt_budget(self):
        """普通模型：三档 effort 映射到不同 temperature，并携带 prompt 预算。"""
        low = build_reasoning_model_kwargs("openai", model="gpt-4o",
                                           config=ReasoningConfig(reasoning_effort="low"))
        assert low["temperature"] == 0.0
        assert low["max_tokens"] == 4096
        assert "reasoning_effort" not in low

        high = build_reasoning_model_kwargs("openai", model="gpt-4o",
                                            config=ReasoningConfig(reasoning_effort="high"))
        assert high["temperature"] == 0.7
        assert build_reasoning_model_kwargs("openai", model="gpt-4o")["temperature"] == 0.2

    def test_reasoning_model_detection(self):
        """模型识别：o1/o3/R1/QwQ 判为推理模型，gpt-4o 不是。"""
        assert is_reasoning_model("o3-mini")
        assert is_reasoning_model("deepseek-r1")
        assert is_reasoning_model("qwq-32b-preview")
        assert not is_reasoning_model("gpt-4o")
        assert not is_reasoning_model("gpt-4.1")


# --------------------------------------------------------------------------
# 6. Tokenizer / 精确 Token 预算
# --------------------------------------------------------------------------
class TestTokenizer:
    def test_counter_protocol_and_empty_text(self):
        """协议一致性：本地实现满足 TokenCounter，空文本计 0。"""
        counter = EnhancedTokenCounter(use_tiktoken=False)
        assert isinstance(counter, TokenCounter)
        assert counter.count("") == 0
        assert counter.count("你好") > 0

    def test_fallback_counts_chinese_and_latin_separately(self):
        """回退估算：中文按字、拉丁按 4 字符/token 分别统计。"""
        counter = EnhancedTokenCounter(use_tiktoken=False)
        assert counter.uses_tiktoken is False
        assert counter.count("你好世界") == 4
        assert counter.count("hello") == 1
        assert counter.count("abcdefgh") == 2
        assert counter.count("你好hello") == 3

    def test_budget_split_greedy(self):
        """预算切分：按原顺序贪心保留，超出预算的记入 dropped。"""
        counter = EnhancedTokenCounter(use_tiktoken=False)
        result = counter.budget_split(["abc", "你好世界", "hi"], limit=4)
        assert isinstance(result, BudgetSplit)
        assert result.kept == ["abc", "hi"]
        assert result.dropped == ["你好世界"]
        assert result.used == 2
        with pytest.raises(ValueError):
            counter.budget_split(["a"], limit=-1)


# --------------------------------------------------------------------------
# 7. 结构化输出强约束
# --------------------------------------------------------------------------
class TestStructured:
    def test_spec_schema_and_constrained_kwargs(self):
        """Schema 生成：从 Pydantic 模型产出 response_format 与格式说明。"""
        spec = StructuredOutputSpec(Answer)
        assert spec.name == "Answer"
        assert "answer" in spec.schema["properties"]
        assert "confidence" in spec.format_instructions()
        kwargs = constrained_model_kwargs(Answer)
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["strict"] is True

    def test_validate_structured_repairs_and_rejects(self):
        """自动修复：提取 JSON 代码块并校验；越界字段/缺字段被拒绝。"""
        raw = '参考输出：\n```json\n{"answer": "在位", "confidence": 0.9}\n```\n以上。'
        parsed = validate_structured(raw, Answer)
        assert isinstance(parsed, Answer) and parsed.answer == "在位"
        assert extract_json("前缀 {\"answer\": \"x\", \"confidence\": 0.5} 后缀")["answer"] == "x"

        with pytest.raises(ValueError):
            validate_structured('{"answer": "x", "confidence": 0.5, "extra": 1}', Answer)
        with pytest.raises(ValueError):
            validate_structured('{"answer": "x", "confidence": 2}', Answer)  # 超出 0~1
        with pytest.raises(ValueError):
            validate_structured("没有 JSON", Answer)


# --------------------------------------------------------------------------
# 8. 模型选型 Benchmark
# --------------------------------------------------------------------------
class TestBenchmark:
    def test_hard_constraints_and_reason(self):
        """硬性约束：质量/成本/P99 门槛先筛选，并产出可读理由。"""
        profiles = [
            ModelProfile(name="premium", quality=9.2, cost_per_1m=8.0, p99_latency_ms=1500),
            ModelProfile(name="cheap", quality=7.0, cost_per_1m=1.0, p99_latency_ms=400),
        ]
        result = select_model(profiles, ModelRequirements(
            min_quality=8.0, max_cost_per_1m=10.0, max_p99_ms=2000,
        ))
        assert result.profile.name == "premium"
        assert result.eligible_count == 1
        assert "质量分 9.2" in result.reason
        assert "加权总分" in result.reason

    def test_weighted_decision_and_tie_break(self):
        """加权决策：延迟权重高时选更快模型；权重自动归一化。"""
        req = ModelRequirements(weights={"latency": 2.0, "cost": 2.0})
        assert req.weights == pytest.approx({"latency": 0.5, "cost": 0.5})
        profiles = [
            ModelProfile(name="slow", quality=8.0, cost_per_1m=2.0, p99_latency_ms=800),
            ModelProfile(name="fast", quality=8.0, cost_per_1m=2.0, p99_latency_ms=200),
        ]
        assert select_model(profiles, req).profile.name == "fast"

        tied = [
            ModelProfile(name="b", quality=8.0, cost_per_1m=1.0, p99_latency_ms=300),
            ModelProfile(name="a", quality=8.0, cost_per_1m=1.0, p99_latency_ms=300),
        ]
        assert select_model(tied).profile.name == "a"  # 得分相同按名称裁决

    def test_no_candidate_raises(self):
        """无候选：没有模型满足门槛时抛出带说明的 ValueError。"""
        profiles = [ModelProfile(name="s", quality=5.0, cost_per_1m=9.0, p99_latency_ms=5000)]
        with pytest.raises(ValueError, match="没有模型满足硬性约束"):
            select_model(profiles, ModelRequirements(min_quality=9.0))
