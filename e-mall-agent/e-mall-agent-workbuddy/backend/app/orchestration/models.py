"""编排模式中传递的结构化数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SubTask(BaseModel):
    """协调者拆分出的子任务。

    Attributes:
        id: 子任务标识。
        description: 子任务描述，作为 worker 的输入。
        worker: 指定执行的 worker 名称；为空时按轮询分配。
    """

    id: str
    description: str
    worker: str = ""

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        if not value:
            raise ValueError("id 不能为空")
        return value


class Evaluation(BaseModel):
    """Evaluator-Optimizer 中评估器的返回结构。"""

    score: float
    feedback: str = ""
    passed: bool | None = None

    @field_validator("score")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def is_accepted(self, threshold: float) -> bool:
        if self.passed is not None:
            return self.passed
        return self.score >= threshold


class WorkerResult(BaseModel):
    """单个 worker 的执行结果，便于 fan-in 汇总与断言。"""

    id: str
    worker: str
    output: str = ""
    error: str = ""
    success: bool = True

    @property
    def ok(self) -> bool:
        return self.success
