"""结构化输出强约束：JSON Schema 生成、严格校验与自动修复。

从 Pydantic 模型生成 schema，提供 OpenAI ``response_format=json_schema``
参数；对模型输出中的 Markdown 代码块 / 前后缀文本做 JSON 提取后严格校验。
"""
from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class StructuredOutputSpec:
    """从一个 Pydantic 模型生成结构化输出约束。"""

    def __init__(self, model: type[BaseModel]) -> None:
        self.model = model

    @property
    def name(self) -> str:
        return self.model.__name__

    @property
    def schema(self) -> dict[str, Any]:
        """模型对应的 JSON Schema。"""
        return self.model.model_json_schema()

    def format_instructions(self) -> str:
        """可拼进 prompt 的格式说明。"""
        return f"请只输出符合以下 JSON Schema 的 JSON：\n{json.dumps(self.schema, ensure_ascii=False)}"

    def to_response_format(self, *, strict: bool = True) -> dict[str, Any]:
        """生成 OpenAI 兼容的 ``response_format`` 参数。"""
        return {
            "type": "json_schema",
            "json_schema": {"name": self.name, "schema": self.schema, "strict": strict},
        }


def extract_json(text: str) -> Any:
    """从可能带 Markdown 代码块或前后缀的文本中提取首个合法 JSON。"""
    if not text or not text.strip():
        raise ValueError("结构化输出为空，无法提取 JSON")

    candidates: list[str] = [text.strip()]
    fenced = _FENCE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for start, char in enumerate(candidate):
            if char not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[start:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("未能从输出中提取合法 JSON")


def validate_structured(
    text: str, model: type[ModelT], *, strict: bool = True
) -> ModelT:
    """严格校验模型输出并返回 Pydantic 实例。

    Args:
        text: 模型原始输出，允许包裹 ```json 代码块或少量前后缀文本。
        model: 目标 Pydantic 模型。
        strict: 为 True 时拒绝 schema 之外的多余字段。

    Raises:
        ValueError: JSON 无法提取、结构不合法或存在多余字段。
    """
    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise ValueError(f"结构化输出应为 JSON 对象，实际为 {type(payload).__name__}")
    if strict:
        extra = set(payload) - set(model.model_fields)
        if extra:
            raise ValueError(f"结构化输出含未声明字段: {', '.join(sorted(extra))}")
    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"结构化输出不符合 {model.__name__} schema: {exc}") from exc


def constrained_model_kwargs(
    spec: StructuredOutputSpec | type[BaseModel], *, strict: bool = True
) -> dict[str, Any]:
    """生成传给模型构造器的 ``response_format`` 参数字典。"""
    resolved = spec if isinstance(spec, StructuredOutputSpec) else StructuredOutputSpec(spec)
    return {"response_format": resolved.to_response_format(strict=strict)}
