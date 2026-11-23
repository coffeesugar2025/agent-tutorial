"""统一规划图工厂。

``create_planning_graph`` 把 ReAct 与 Plan-and-Solve 两种模式编成统一的
LangGraph 图，对外只暴露 ``ainvoke({"goal": ..., "user": ...})`` 接口。
"""
from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .executor import PlanAndSolveExecutor
from .planner import PlanAndSolvePlanner
from .react import ReActLoop


class PlanningState(TypedDict):
    """统一规划图的状态。"""

    goal: str
    user: Any
    mode: str
    answer: str
    trace: list[dict[str, Any]]
    terminated_reason: str
    metadata: dict[str, Any]


def create_planning_graph(
    mode: str = "react",
    *,
    planner: PlanAndSolvePlanner | None = None,
    tools: list[BaseTool] | None = None,
    max_steps: int = 6,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """创建统一入口的规划图。

    Args:
        mode: ``react`` 或 ``plan_solve``。
        planner: 可选规划器；两种模式共用。
        tools: 可选工具列表；缺省时各组件加载本地工具。
        max_steps: ReAct 模式的最大步数。
        checkpointer: 可选检查点存储。

    Returns:
        编译后的 LangGraph 图，支持 ``ainvoke({"goal":..., "user":...})``。

    Raises:
        ValueError: mode 不是受支持的值。
    """
    if mode not in ("react", "plan_solve"):
        raise ValueError("mode 必须是 react 或 plan_solve")
    shared_planner = planner or PlanAndSolvePlanner()
    react = ReActLoop(planner=shared_planner, tools=tools, max_steps=max_steps)
    executor = PlanAndSolveExecutor(planner=shared_planner, tools=tools)

    async def execute(state: PlanningState) -> dict[str, Any]:
        goal = state.get("goal", "")
        user = state.get("user")
        active_mode = state.get("mode") or mode
        if active_mode == "react":
            result = await react.run(goal, user)
            return {
                "answer": result.answer,
                "trace": [step.model_dump() for step in result.trajectory],
                "terminated_reason": result.terminated_reason,
                "metadata": {"mode": "react", "steps_used": result.steps_used},
            }
        report = await executor.run(goal, user)
        return {
            "answer": report.answer,
            "trace": [step.model_dump() for step in report.steps],
            "terminated_reason": report.terminated_reason,
            "metadata": {
                "mode": "plan_solve",
                "success_count": report.success_count,
                "failed_count": report.failed_count,
            },
        }

    async def finalize(state: PlanningState) -> dict[str, Any]:
        """汇总节点：结果已在 execute 中整理，这里保持结构完整。"""
        return {}

    builder = StateGraph(PlanningState)
    builder.add_node("execute", execute)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
