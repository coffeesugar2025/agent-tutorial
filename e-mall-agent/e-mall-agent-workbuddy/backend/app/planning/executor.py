"""Plan-and-Solve 执行器。

先由规划器生成结构化计划，再按依赖关系逐步执行。某步失败时，依赖它的
后续步骤被跳过；若提供降级方案，则失败步骤转为降级结果并继续执行。
"""
from __future__ import annotations

import inspect
from typing import Any

from .common import build_action_input, call_tool, is_failure
from .models import ExecutionReport, Plan, PlanStep, StepResult
from .planner import PlanAndSolvePlanner

Fallback = Any  # 常量或可调用对象（同步/异步）


class PlanAndSolveExecutor:
    """先规划后执行的编排器。

    Args:
        planner: 规划器；默认 ``PlanAndSolvePlanner``。
        tools: 绑定的工具列表；默认加载本地工具。
    """

    def __init__(
        self,
        planner: PlanAndSolvePlanner | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        self.planner = planner or PlanAndSolvePlanner()
        if tools is None:
            from ..agents.tools import local_tools

            tools = local_tools()
        self.tools: list[Any] = list(tools)

    @staticmethod
    def _topo_order(steps: list[PlanStep]) -> list[PlanStep]:
        """按 ``depends_on`` 做稳定拓扑排序。"""
        remaining = list(steps)
        done: set[str] = set()
        ordered: list[PlanStep] = []
        while remaining:
            progressed = False
            for step in list(remaining):
                if all(dep in done for dep in step.depends_on):
                    ordered.append(step)
                    done.add(step.id)
                    remaining.remove(step)
                    progressed = True
            if not progressed:
                ordered.extend(remaining)
                break
        return ordered

    async def _resolve_fallback(
        self, fallback: Fallback, step: PlanStep, output: str
    ) -> str:
        """解析降级方案：可调用则执行，否则作为常量字符串。"""
        if callable(fallback):
            try:
                value = fallback(step.id, output)
            except TypeError:
                value = fallback()
            if inspect.isawaitable(value):
                value = await value
            return str(value)
        return str(fallback)

    async def execute_plan(
        self, plan: Plan, user: Any = None, *, fallback: Fallback = None
    ) -> ExecutionReport:
        """执行已有计划。

        Args:
            plan: 待执行的计划。
            user: 可选用户对象。
            fallback: 步骤失败时的降级值或降级函数。

        Returns:
            结构化的 ``ExecutionReport``。
        """
        results: list[StepResult] = []
        failed_ids: set[str] = set()

        for step in self._topo_order(plan.steps):
            if any(dep in failed_ids for dep in step.depends_on):
                results.append(StepResult(
                    step_id=step.id,
                    status="skipped",
                    tool=step.tool_hint,
                    error="前置步骤失败，跳过执行",
                ))
                failed_ids.add(step.id)
                continue

            if not step.tool_hint:
                results.append(StepResult(
                    step_id=step.id,
                    status="success",
                    tool="",
                    output=f"直接回答：{plan.goal}",
                ))
                continue

            output = call_tool(
                self.tools, step.tool_hint,
                build_action_input(step.tool_hint, plan.goal, user),
            )
            if is_failure(output):
                if fallback is not None:
                    degraded = await self._resolve_fallback(fallback, step, output)
                    results.append(StepResult(
                        step_id=step.id,
                        status="degraded",
                        tool=step.tool_hint,
                        output=degraded,
                        error=output,
                    ))
                else:
                    failed_ids.add(step.id)
                    results.append(StepResult(
                        step_id=step.id,
                        status="failed",
                        tool=step.tool_hint,
                        output=output,
                        error="工具执行失败",
                    ))
            else:
                results.append(StepResult(
                    step_id=step.id,
                    status="success",
                    tool=step.tool_hint,
                    output=output,
                ))

        # 保持与计划原始顺序一致的输出
        order = {step.id: index for index, step in enumerate(plan.steps)}
        results.sort(key=lambda r: order.get(r.step_id, 0))

        outputs = [r.output for r in results if r.output and r.status in ("success", "degraded")]
        answer = "\n\n".join(outputs) if outputs else "执行失败，未能完成目标。"
        if any(r.status == "skipped" for r in results):
            reason = "因前置步骤失败而跳过后续步骤"
        elif any(r.status == "degraded" for r in results):
            reason = "部分步骤经降级完成"
        elif any(r.status == "failed" for r in results):
            reason = "存在失败步骤"
        else:
            reason = "全部步骤执行成功"
        return ExecutionReport(
            goal=plan.goal, steps=results, answer=answer, terminated_reason=reason
        )

    async def run(
        self, goal: str, user: Any = None, *, fallback: Fallback = None
    ) -> ExecutionReport:
        """先规划再执行用户目标。

        Args:
            goal: 用户目标。
            user: 可选用户对象。
            fallback: 失败步骤的降级方案。

        Returns:
            结构化的执行报告。
        """
        plan = self.planner.plan(goal, user)
        return await self.execute_plan(plan, user, fallback=fallback)
