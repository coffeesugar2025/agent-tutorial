"""规划与执行过程中使用的结构化数据模型。

所有模型基于 Pydantic v2，便于被 ``PydanticOutputParser`` 解析，
也便于在测试与可视化界面中序列化。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """计划中的单个步骤。

    Attributes:
        id: 步骤唯一标识，形如 ``s1``。
        description: 该步骤的自然语言描述。
        tool_hint: 建议使用的工具名；为空表示直接回答。
        depends_on: 前置步骤的 id 列表。
    """

    id: str
    description: str
    tool_hint: str = ""
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """结构化执行计划。

    Attributes:
        goal: 原始用户目标。
        steps: 按建议执行顺序排列的步骤列表。
    """

    goal: str
    steps: list[PlanStep] = Field(default_factory=list)


class PlanOutput(BaseModel):
    """供 ``PydanticOutputParser`` 解析的模型输出。"""

    steps: list[PlanStep] = Field(
        default_factory=list, description="按执行顺序排列的步骤，每步含 id、描述、工具提示与依赖"
    )


class ReActStep(BaseModel):
    """ReAct 循环中的一轮轨迹记录。

    Attributes:
        thought: 本轮推理。
        action: 本轮选择的动作（工具名）。
        action_input: 传给工具的参数。
        observation: 工具返回的观察结果。
    """

    thought: str
    action: str
    action_input: dict[str, Any] = Field(default_factory=dict)
    observation: str = ""


class ReActResult(BaseModel):
    """ReAct 循环的最终结果。

    Attributes:
        answer: 汇总后的自然语言答案。
        trajectory: 完整的 Thought/Action/Observation 轨迹。
        steps_used: 实际使用的动作步数。
        terminated_reason: 终止原因。
    """

    answer: str
    trajectory: list[ReActStep] = Field(default_factory=list)
    steps_used: int = 0
    terminated_reason: str = ""


class StepResult(BaseModel):
    """计划中单个步骤的执行结果。

    Attributes:
        step_id: 对应步骤 id。
        status: ``success`` / ``failed`` / ``skipped`` / ``degraded``。
        tool: 实际调用的工具名。
        output: 工具输出或降级结果。
        error: 失败原因。
    """

    step_id: str
    status: str
    tool: str = ""
    output: str = ""
    error: str = ""


class ExecutionReport(BaseModel):
    """Plan-and-Solve 的结构化执行报告。

    Attributes:
        goal: 原始目标。
        steps: 逐步执行结果。
        answer: 汇总后的自然语言答案。
        terminated_reason: 执行终止原因。
    """

    goal: str
    steps: list[StepResult] = Field(default_factory=list)
    answer: str = ""
    terminated_reason: str = ""

    @property
    def success_count(self) -> int:
        """成功步骤数。"""
        return sum(1 for s in self.steps if s.status == "success")

    @property
    def failed_count(self) -> int:
        """失败步骤数。"""
        return sum(1 for s in self.steps if s.status == "failed")

    @property
    def skipped_count(self) -> int:
        """因依赖失败而跳过的步骤数。"""
        return sum(1 for s in self.steps if s.status == "skipped")

    @property
    def degraded_count(self) -> int:
        """经降级后完成的步骤数。"""
        return sum(1 for s in self.steps if s.status == "degraded")
