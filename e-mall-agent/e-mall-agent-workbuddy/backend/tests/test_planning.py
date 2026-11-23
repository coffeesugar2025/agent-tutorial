"""Planning 能力专项测试：结构化规划、ReAct 循环、Plan-and-Solve 执行与统一图入口。

每个用例都用中文 docstring 说明「知识点 -> 验证点」。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from app.planning import (
    ExecutionReport,
    Plan,
    PlanAndSolveExecutor,
    PlanAndSolvePlanner,
    PlanStep,
    ReActLoop,
    ReActResult,
    create_planning_graph,
)


def _named_tool(name: str, func: Any) -> StructuredTool:
    """把普通函数包装成指定名称的 LangChain 工具。"""
    return StructuredTool.from_function(func=func, name=name, description=name)


def _search_products(query: str) -> str:
    """搜索商品假工具。"""
    return json.dumps([{"id": "P001", "name": "耳机", "price": 899, "stock": 9}],
                      ensure_ascii=False)


def _check_inventory(product_id: str) -> str:
    """查询库存假工具。"""
    return json.dumps({"available": True, "product_id": product_id, "stock": 9},
                      ensure_ascii=False)


def _create_order(customer_id: str, items_json: str) -> str:
    """下单假工具。"""
    return json.dumps({"order_id": "O9999", "customer_id": customer_id,
                       "status": "created", "items": json.loads(items_json)},
                      ensure_ascii=False)


def _fake_tools() -> list[StructuredTool]:
    return [
        _named_tool("search_products", _search_products),
        _named_tool("check_inventory", _check_inventory),
        _named_tool("create_order", _create_order),
    ]


class TestPlanAndSolvePlanner:
    def test_plan_steps_count_and_dependencies(self):
        """结构化规划：复合目标拆成多步，且后续步骤依赖前一步。"""
        plan = PlanAndSolvePlanner().plan("查一下 P001 库存然后下单")
        assert isinstance(plan, Plan)
        assert len(plan.steps) == 2
        assert all(isinstance(s, PlanStep) for s in plan.steps)
        assert plan.steps[0].tool_hint == "check_inventory"
        assert plan.steps[1].tool_hint == "create_order"
        assert plan.steps[0].depends_on == []
        assert plan.steps[1].depends_on == [plan.steps[0].id]

    def test_plan_single_step_for_simple_goal(self):
        """简单目标：单意图目标只拆出一步。"""
        plan = PlanAndSolvePlanner().plan("申请退款 O1001")
        assert len(plan.steps) == 1
        assert plan.steps[0].tool_hint == "initiate_refund"

    def test_plan_general_step_for_unknown_goal(self):
        """未知意图：无工具匹配时生成直接回答的通用步骤。"""
        plan = PlanAndSolvePlanner().plan("你好呀")
        assert len(plan.steps) == 1
        assert plan.steps[0].tool_hint == ""
        assert "直接回答" in plan.steps[0].description

    def test_lcel_chain_uses_pydantic_parser(self):
        """LCEL 管道：prompt -> 结构化输出 -> PydanticOutputParser 可解析。"""
        planner = PlanAndSolvePlanner()
        chain = planner.chain
        assert len(chain.steps) == 3
        output = chain.invoke({"goal": "推荐耳机"})
        assert all(isinstance(s, PlanStep) for s in output.steps)

    @pytest.mark.asyncio
    async def test_async_plan(self):
        """异步规划：aplan 与 plan 产出一致的步骤结构。"""
        planner = PlanAndSolvePlanner()
        plan = await planner.aplan("查 P001 库存")
        assert [s.tool_hint for s in plan.steps] == ["check_inventory"]


class TestReActLoop:
    @pytest.mark.asyncio
    async def test_react_multiple_tool_calls_trajectory(self):
        """ReAct 轨迹：多轮工具调用产生 Thought/Action/Observation 记录。"""
        loop = ReActLoop(planner=PlanAndSolvePlanner(), tools=_fake_tools(), max_steps=5)
        result = await loop.run("查一下 P001 库存然后搜索耳机")
        assert isinstance(result, ReActResult)
        assert result.steps_used == 2
        assert result.terminated_reason == "任务完成"
        assert [s.action for s in result.trajectory] == ["search_products", "check_inventory"]
        assert all(s.thought and s.observation for s in result.trajectory)
        assert "P001" in result.answer

    @pytest.mark.asyncio
    async def test_react_max_steps_termination(self):
        """最大步数：达到上限后提前终止，不再执行剩余动作。"""
        loop = ReActLoop(planner=PlanAndSolvePlanner(), tools=_fake_tools(), max_steps=1)
        result = await loop.run("推荐耳机，查库存，然后下单")
        assert result.steps_used == 1
        assert len(result.trajectory) == 1
        assert "最大步数" in result.terminated_reason

    def test_react_graph_nodes_and_checkpointer(self):
        """LangGraph：编译后的图含 think/act/observe/finalize 节点。"""
        loop = ReActLoop(tools=_fake_tools())
        nodes = set(loop.get_graph().get_graph().nodes)
        assert {"think", "act", "observe", "finalize"} <= nodes


class TestPlanAndSolveExecutor:
    @pytest.mark.asyncio
    async def test_executor_runs_all_steps(self):
        """顺序执行：依赖步骤按拓扑顺序全部成功。"""
        executor = PlanAndSolveExecutor(planner=PlanAndSolvePlanner(), tools=_fake_tools())
        report = await executor.run("查一下 P001 库存然后下单")
        assert isinstance(report, ExecutionReport)
        assert report.success_count == 2
        assert report.failed_count == 0
        assert report.terminated_reason == "全部步骤执行成功"

    @pytest.mark.asyncio
    async def test_executor_failure_skips_dependents(self):
        """失败跳过：首步失败后，依赖它的后续步骤被标记为 skipped。"""
        def broken_inventory(product_id: str) -> str:
            return json.dumps({"error": "库存服务不可用"}, ensure_ascii=False)

        tools = [
            _named_tool("check_inventory", broken_inventory),
            _named_tool("create_order", _create_order),
        ]
        executor = PlanAndSolveExecutor(planner=PlanAndSolvePlanner(), tools=tools)
        report = await executor.run("查一下 P001 库存然后下单")
        assert report.failed_count == 1
        assert report.skipped_count == 1
        assert "跳过" in report.terminated_reason

    @pytest.mark.asyncio
    async def test_executor_failure_degrades_and_continues(self):
        """失败降级：提供 fallback 后，失败步骤降级且后续步骤继续执行。"""
        def broken_inventory(product_id: str) -> str:
            return json.dumps({"error": "库存服务不可用"}, ensure_ascii=False)

        tools = [
            _named_tool("check_inventory", broken_inventory),
            _named_tool("create_order", _create_order),
        ]
        executor = PlanAndSolveExecutor(planner=PlanAndSolvePlanner(), tools=tools)
        report = await executor.run("查一下 P001 库存然后下单", fallback="降级答案")
        assert report.degraded_count == 1
        assert report.success_count == 1
        assert report.skipped_count == 0
        assert "降级" in report.terminated_reason


class TestPlanningGraphFactory:
    @pytest.mark.asyncio
    async def test_graph_react_mode(self):
        """统一入口：react 模式 ainvoke 返回答案、轨迹与元数据。"""
        graph = create_planning_graph("react", planner=PlanAndSolvePlanner(), tools=_fake_tools())
        out = await graph.ainvoke({"goal": "查一下 P001 库存", "user": None})
        assert out["answer"]
        assert out["metadata"]["mode"] == "react"
        assert out["trace"][0]["action"] == "check_inventory"

    @pytest.mark.asyncio
    async def test_graph_plan_solve_mode(self):
        """统一入口：plan_solve 模式返回执行报告元数据。"""
        graph = create_planning_graph("plan_solve", planner=PlanAndSolvePlanner(),
                                      tools=_fake_tools())
        out = await graph.ainvoke({"goal": "查一下 P001 库存然后下单", "user": None})
        assert out["metadata"]["mode"] == "plan_solve"
        assert out["metadata"]["success_count"] == 2
        assert len(out["trace"]) == 2

    @pytest.mark.asyncio
    async def test_graph_with_checkpointer(self):
        """检查点：传入 InMemorySaver 后可用 thread_id 隔离会话。"""
        from langgraph.checkpoint.memory import InMemorySaver

        graph = create_planning_graph("react", planner=PlanAndSolvePlanner(),
                                      tools=_fake_tools(), checkpointer=InMemorySaver())
        out = await graph.ainvoke(
            {"goal": "查一下 P001 库存", "user": None},
            {"configurable": {"thread_id": "planning-test-thread"}},
        )
        assert out["answer"]

    def test_invalid_mode_raises(self):
        """参数校验：不支持的 mode 抛出 ValueError。"""
        with pytest.raises(ValueError):
            create_planning_graph("unknown")
