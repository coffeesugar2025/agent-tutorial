"""ReAct 循环：Thought -> Action -> Observation。

使用 LangGraph ``StateGraph`` 实现，节点为 think/act/observe/finalize，
条件边根据剩余动作与最大步数在 continue/end 之间路由，并用
``InMemorySaver`` 保存检查点。
"""
from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .common import build_action_input, call_tool
from .models import Plan, ReActResult, ReActStep
from .planner import PlanAndSolvePlanner


class ReActState(TypedDict):
    """ReAct 图的状态。"""

    goal: str
    user: Any
    pending: dict[str, Any]
    actions: list[dict[str, Any]]
    trajectory: list[ReActStep]
    steps_used: int
    max_steps: int
    answer: str
    terminated_reason: str
    last_observation: str


class ReActLoop:
    """LangGraph 驱动的 ReAct 推理循环。

    Args:
        planner: 规划器，用于把目标转成动作序列；默认 ``PlanAndSolvePlanner``。
        tools: 绑定的工具列表；默认加载项目内的本地工具。
        max_steps: 最大动作步数，作为终止条件。
    """

    def __init__(
        self,
        planner: PlanAndSolvePlanner | None = None,
        tools: list[Any] | None = None,
        max_steps: int = 6,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.planner = planner or PlanAndSolvePlanner()
        self.max_steps = max_steps
        if tools is None:
            from ..agents.tools import local_tools

            tools = local_tools()
        self.tools: list[Any] = list(tools)
        self.graph = self._build_graph()

    def _actions_from_plan(self, plan: Plan, user: Any = None) -> list[dict[str, Any]]:
        """把计划步骤转成待执行的动作队列。"""
        actions: list[dict[str, Any]] = []
        for step in plan.steps:
            actions.append({
                "id": step.id,
                "description": step.description,
                "tool_hint": step.tool_hint,
                "action_input": build_action_input(step.tool_hint, plan.goal, user),
            })
        return actions

    def _build_graph(self) -> Any:
        """构建并编译 ReAct 状态图（含内存检查点）。"""

        async def think(state: ReActState) -> dict[str, Any]:
            actions = list(state.get("actions", []))
            if not actions:
                return {}
            action = actions.pop(0)
            thought = f"为了完成目标，我需要{action['description']}。"
            return {
                "actions": actions,
                "pending": {
                    "action": action["tool_hint"],
                    "action_input": action["action_input"],
                    "thought": thought,
                    "description": action["description"],
                },
            }

        async def act(state: ReActState) -> dict[str, Any]:
            pending = state["pending"]
            tool_hint = pending["action"]
            if not tool_hint:
                observation = f"直接回答：{state['goal']}"
            else:
                observation = call_tool(self.tools, tool_hint, pending["action_input"])
            return {
                "steps_used": state.get("steps_used", 0) + 1,
                "last_observation": observation,
            }

        async def observe(state: ReActState) -> dict[str, Any]:
            pending = state["pending"]
            step = ReActStep(
                thought=pending["thought"],
                action=pending["action"],
                action_input=pending["action_input"],
                observation=state.get("last_observation", ""),
            )
            return {"trajectory": list(state.get("trajectory", [])) + [step]}

        def route(state: ReActState) -> str:
            if state.get("steps_used", 0) >= state["max_steps"] or not state.get("actions"):
                return "finalize"
            return "think"

        async def finalize(state: ReActState) -> dict[str, Any]:
            observations = [s.observation for s in state.get("trajectory", []) if s.observation]
            answer = "\n\n".join(observations) or "已完成分析。"
            if state.get("steps_used", 0) >= state["max_steps"] and state.get("actions"):
                reason = f"达到最大步数 {state['max_steps']}"
            elif not state.get("actions"):
                reason = "任务完成"
            else:
                reason = "循环终止"
            return {"answer": answer, "terminated_reason": reason}

        builder = StateGraph(ReActState)
        builder.add_node("think", think)
        builder.add_node("act", act)
        builder.add_node("observe", observe)
        builder.add_node("finalize", finalize)
        builder.add_edge(START, "think")
        builder.add_edge("think", "act")
        builder.add_edge("act", "observe")
        builder.add_conditional_edges("observe", route, {"think": "think", "finalize": "finalize"})
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=InMemorySaver())

    def get_graph(self) -> Any:
        """返回编译后的 LangGraph 图，便于检查节点结构。"""
        return self.graph

    async def run(
        self,
        goal: str,
        user: Any = None,
        *,
        thread_id: str | None = None,
        max_steps: int | None = None,
    ) -> ReActResult:
        """执行 ReAct 循环并返回结构化结果。

        Args:
            goal: 用户目标。
            user: 可选用户对象，用于生成工具参数。
            thread_id: 检查点线程 id；缺省时随机生成。
            max_steps: 覆盖构造时的最大步数。

        Returns:
            含答案、完整轨迹、步数与终止原因的 ``ReActResult``。
        """
        plan = self.planner.plan(goal, user)
        limit = self.max_steps if max_steps is None else max_steps
        initial: ReActState = {
            "goal": goal,
            "user": user,
            "pending": {},
            "actions": self._actions_from_plan(plan, user),
            "trajectory": [],
            "steps_used": 0,
            "max_steps": limit,
            "answer": "",
            "terminated_reason": "",
            "last_observation": "",
        }
        config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}}
        final = await self.graph.ainvoke(initial, config)
        return ReActResult(
            answer=final.get("answer", ""),
            trajectory=list(final.get("trajectory", [])),
            steps_used=final.get("steps_used", 0),
            terminated_reason=final.get("terminated_reason", ""),
        )
