"""本地任务委派 stub：提交任务 -> 状态流转 -> 结果。

这是应用层的协议骨架，用内存状态机模拟 A2A/ACP/ANP 的任务委派语义；
真实网络传输可用同一接口替换成适配器（例如把 handler 换成 RPC 调用）。
"""
from __future__ import annotations

import inspect
import threading
from collections.abc import Callable
from typing import Any

from .models import AgentTask, TaskState
from .registry import AgentCardRegistry

Handler = Callable[[str], Any]


class TaskFlow:
    """显式的任务状态机，便于逐步断言每一次状态流转。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, AgentTask] = {}
        self._counter = 0

    def submit(self, agent: str, task: str) -> AgentTask:
        """创建 SUBMITTED 状态的任务，id 为确定性的 ``task-0001``。"""
        with self._lock:
            self._counter += 1
            record = AgentTask(id=f"task-{self._counter:04d}", agent=agent, task=task,
                               history=[TaskState.SUBMITTED.value])
            self._tasks[record.id] = record
            return record

    def start(self, task_id: str) -> AgentTask:
        """SUBMITTED -> WORKING。"""
        return self._get(task_id).transition(TaskState.WORKING)

    def complete(self, task_id: str, result: str) -> AgentTask:
        """WORKING -> COMPLETED。"""
        return self._get(task_id).transition(TaskState.COMPLETED, result=result)

    def fail(self, task_id: str, error: str) -> AgentTask:
        """WORKING -> FAILED。"""
        return self._get(task_id).transition(TaskState.FAILED, error=error)

    def cancel(self, task_id: str) -> AgentTask:
        """SUBMITTED/WORKING -> CANCELED。"""
        return self._get(task_id).transition(TaskState.CANCELED)

    def get(self, task_id: str) -> AgentTask:
        """按 id 读取任务快照。"""
        return self._get(task_id)

    def _get(self, task_id: str) -> AgentTask:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(f"未知任务: {task_id}")
            return self._tasks[task_id]


class LocalTaskDelegator:
    """把任务委派给本地 handler，并自动完成状态流转。"""

    def __init__(
        self,
        registry: AgentCardRegistry | None = None,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        self.registry = registry
        self.handlers = dict(handlers or {})
        self.flow = TaskFlow()

    def register_handler(self, agent: str, handler: Handler) -> None:
        """为某个 Agent 绑定本地处理函数。"""
        self.handlers[agent] = handler

    def submit(self, agent: str, task: str) -> AgentTask:
        """同步委派：校验注册 -> SUBMITTED -> WORKING -> COMPLETED/FAILED。"""
        self._check_agent(agent)
        record = self.flow.submit(agent, task)
        self.flow.start(record.id)
        try:
            result = self.handlers[agent](task)
            if inspect.isawaitable(result):
                raise TypeError("检测到异步 handler，请改用 await asubmit(...)")
            return self.flow.complete(record.id, str(result))
        except Exception as exc:  # handler 失败也走明确的状态流转
            return self.flow.fail(record.id, str(exc))

    async def asubmit(self, agent: str, task: str) -> AgentTask:
        """``submit`` 的异步版本，自动 await 异步 handler。"""
        self._check_agent(agent)
        record = self.flow.submit(agent, task)
        self.flow.start(record.id)
        try:
            result = self.handlers[agent](task)
            if inspect.isawaitable(result):
                result = await result
            return self.flow.complete(record.id, str(result))
        except Exception as exc:
            return self.flow.fail(record.id, str(exc))

    def _check_agent(self, agent: str) -> None:
        if agent not in self.handlers:
            raise KeyError(f"Agent 没有本地 handler: {agent}")
        if self.registry is not None:
            self.registry.require(agent)
