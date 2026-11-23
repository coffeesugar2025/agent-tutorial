"""Agent 通信协议骨架包：A2A / ACP / ANP。

仅实现应用层语义（Agent Card、注册发现、任务状态流转与本地委派），
真实网络传输是可替换的适配器，不在本包内实现。
"""
from __future__ import annotations

from .delegate import LocalTaskDelegator, TaskFlow
from .models import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    AgentTask,
    TaskState,
)
from .registry import AgentCardRegistry

__all__ = [
    "AgentCapabilities",
    "AgentCard",
    "AgentCardRegistry",
    "AgentSkill",
    "AgentTask",
    "LocalTaskDelegator",
    "TaskFlow",
    "TaskState",
]
