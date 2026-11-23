"""Agent 通信协议的数据模型（Agent Card 与任务状态机）。

注意：这是**应用层的协议骨架**。字段对齐 A2A Agent Card 的核心语义
（name/version/capabilities/skills/endpoint），但不实现任何网络传输；
真实网络层可在保持这些模型不变的前提下替换为适配器。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentSkill(BaseModel):
    """Agent 声明的一项能力。"""

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class AgentCapabilities(BaseModel):
    """Agent 支持的协议能力开关。"""

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = True


class AgentCard(BaseModel):
    """Agent Card 元数据：服务发现用的自描述名片。"""

    name: str
    version: str = "1.0.0"
    description: str = ""
    endpoint: str = ""
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    protocol: str = "a2a"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("AgentCard.name 不能为空")
        return value

    def skill_ids(self) -> list[str]:
        """返回该卡声明的全部技能 id。"""
        return [skill.id for skill in self.skills]


class TaskState(str, Enum):
    """本地任务状态机的合法状态。"""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
_ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.CANCELED},
    TaskState.WORKING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED},
}


class AgentTask(BaseModel):
    """一次本地任务委派的状态快照。"""

    id: str
    agent: str
    task: str
    state: TaskState = TaskState.SUBMITTED
    result: str = ""
    error: str = ""
    history: list[str] = Field(default_factory=list)

    def transition(
        self, target: TaskState, *, result: str = "", error: str = ""
    ) -> "AgentTask":
        """按合法状态流转并写入历史；非法流转抛 ValueError。"""
        if self.state in _TERMINAL:
            raise ValueError(f"终态 {self.state.value} 不能再次流转")
        if target not in _ALLOWED.get(self.state, set()):
            raise ValueError(f"非法状态流转: {self.state.value} -> {target.value}")
        self.state = target
        self.result = result or self.result
        self.error = error or self.error
        self.history.append(target.value)
        return self

    @property
    def is_terminal(self) -> bool:
        """任务是否已处于终态。"""
        return self.state in _TERMINAL
