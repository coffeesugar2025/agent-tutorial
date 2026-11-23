"""Agent 工程专项测试：反思自纠错、五类编排模式、A2A 通信骨架、Tool RAG 与 Prompt 版本管理。

每个用例用中文 docstring 说明「知识点 -> 验证点」。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from app.a2a import (
    AgentCapabilities,
    AgentCard,
    AgentCardRegistry,
    AgentSkill,
    LocalTaskDelegator,
    TaskFlow,
    TaskState,
)
from app.agents.tool_retriever import ToolRetriever
from app.domain.models import User
from app.orchestration import (
    ALL_PATTERNS,
    EVALUATOR_OPTIMIZER,
    ORCHESTRATOR_WORKERS,
    PARALLELIZATION,
    PROMPT_CHAINING,
    ROUTING,
    Evaluation,
    build_pattern,
)
from app.prompts import (
    PromptRegistry,
    audio_block,
    build_content,
    image_url_block,
    text_block,
)
from app.reflection import Critique, ReflexionLoop, SelfConsistency, majority_vote


# --------------------------------------------------------------------------
# 1. 反思与自纠错
# --------------------------------------------------------------------------
class TestReflexion:
    def test_revises_until_score_threshold(self):
        """Reflexion：低分触发带反馈的修订再执行，达标后停止。"""
        answers = iter(["初稿", "修订稿"])

        def executor(task: str, feedback: str | None) -> str:
            assert task == "写摘要"
            assert feedback is None or "补充" in feedback
            return next(answers)

        def critic(task: str, answer: str) -> dict[str, Any]:
            return {"score": 0.4 if answer == "初稿" else 0.95,
                    "feedback": "请补充细节"}

        loop = ReflexionLoop(executor, critic, max_iterations=4, score_threshold=0.8)
        result = loop.run("写摘要")
        assert result.answer == "修订稿"
        assert result.iterations_used == 2
        assert result.scores == [0.4, 0.95]
        assert result.trace[0].revised is False
        assert result.trace[1].revised is True
        assert "达标" in result.terminated_reason

    def test_stops_at_max_iterations(self):
        """停止条件：一直不达标时按最大迭代终止，且不允许 patience 提前停止。"""
        loop = ReflexionLoop(
            lambda task, feedback: "答案",
            lambda task, answer: Critique(score=0.1, feedback="再想想"),
            max_iterations=3, patience=0,
        )
        result = loop.run("任意任务")
        assert result.iterations_used == 3
        assert result.scores == [0.1, 0.1, 0.1]
        assert "最大迭代次数 3" in result.terminated_reason

    @pytest.mark.asyncio
    async def test_async_executor_and_critic(self):
        """异步注入：executor 与 critic 均可为协程，arun 自动 await。"""
        async def executor(task: str, feedback: str | None) -> str:
            return "异步答案"

        async def critic(task: str, answer: str) -> tuple[float, str]:
            return 0.9, "很好"

        result = await ReflexionLoop(executor, critic).arun("任务")
        assert result.answer == "异步答案"
        assert result.scores == [0.9]
        assert result.iterations_used == 1

    def test_invalid_max_iterations_raises(self):
        """参数校验：max_iterations 必须 >= 1。"""
        with pytest.raises(ValueError):
            ReflexionLoop(lambda t, f: "", lambda t, a: 0.5, max_iterations=0)

    def test_self_consistency_majority_and_tie(self):
        """Self-Consistency：多数表决胜出；平票时按答案文本确定性裁决。"""
        result = majority_vote(["A", " A ", "B", "A"])
        assert result.answer == "A"
        assert result.votes == {"A": 3, "B": 1}
        assert result.confidence == pytest.approx(0.75)
        assert result.tied is False

        tie = majority_vote(["乙", "甲"])
        assert tie.answer in {"甲", "乙"}  # 平票按文本确定性裁决
        assert tie.tied is True

    def test_self_consistency_sampler(self):
        """采样器注入：按次数采样后投票；空样本与非法次数被拒绝。"""
        sampler = SelfConsistency(lambda task: "42" if task == "答案" else "未知")
        result = sampler.sample_and_vote("答案", n=5)
        assert result.answer == "42"
        assert result.total == 5
        with pytest.raises(ValueError):
            sampler.sample_and_vote("答案", n=0)
        with pytest.raises(ValueError):
            majority_vote([])


# --------------------------------------------------------------------------
# 2. 编排模式
# --------------------------------------------------------------------------
class TestOrchestration:
    @pytest.mark.asyncio
    async def test_parallel_pattern_fan_out_fan_in(self):
        """Parallelization：多个 worker 扇出并行，扇入时按自定义汇总。"""
        graph = build_pattern(
            PARALLELIZATION,
            workers=[lambda t: f"A({t})", lambda t: f"B({t})"],
            aggregator=lambda results: "|".join(results),
        )
        out = await graph.ainvoke({"task": "X"})
        assert out["answer"] == "A(X)|B(X)"
        assert len(out["results"]) == 2

    @pytest.mark.asyncio
    async def test_orchestrator_workers_dynamic_dispatch(self):
        """Orchestrator-Workers：协调者拆分任务，按指定 worker 动态分发。"""
        graph = build_pattern(
            ORCHESTRATOR_WORKERS,
            orchestrator=lambda t: [
                {"id": "s1", "description": "查库存", "worker": "stock"},
                {"id": "s2", "description": "查订单", "worker": "order"},
            ],
            workers={"stock": lambda t: f"库存:{t}", "order": lambda t: f"订单:{t}"},
        )
        out = await graph.ainvoke({"task": "复合任务"})
        assert [r["worker"] for r in out["results"]] == ["stock", "order"]
        assert out["answer"] == "库存:查库存\n订单:查订单"

    @pytest.mark.asyncio
    async def test_evaluator_optimizer_revises_until_acceptable(self):
        """Evaluator-Optimizer：评估不达标则带反馈修订，达标即停止。"""
        calls = {"n": 0}

        def generator(task: str, feedback: str) -> str:
            calls["n"] += 1
            return f"版本{calls['n']}" + (f"[{feedback}]" if feedback else "")

        def evaluator(task: str, draft: str) -> Evaluation:
            return Evaluation(score=0.3 if calls["n"] == 1 else 0.9, feedback="更详细")

        graph = build_pattern(EVALUATOR_OPTIMIZER, generator=generator,
                              evaluator=evaluator, max_iterations=3, score_threshold=0.8)
        out = await graph.ainvoke({"task": "写文案"})
        assert out["iterations"] == 2
        assert out["answer"] == "版本2[更详细]"
        assert out["terminated_reason"] == "评估达标"

    @pytest.mark.asyncio
    async def test_evaluator_optimizer_max_iteration_cap(self):
        """上限保护：评估始终不达标时不会无限循环。"""
        graph = build_pattern(
            EVALUATOR_OPTIMIZER,
            generator=lambda task, feedback: "草稿",
            evaluator=lambda task, draft: (0.1, "再改"),
            max_iterations=2,
        )
        out = await graph.ainvoke({"task": "T"})
        assert out["iterations"] == 2
        assert "最大迭代次数 2" in out["terminated_reason"]

    @pytest.mark.asyncio
    async def test_factory_exposes_five_official_patterns(self):
        """工厂常量：官方五类模式齐全，Routing 与 Prompt Chaining 也可构造。"""
        assert len(ALL_PATTERNS) == 5
        assert {PROMPT_CHAINING, ROUTING, PARALLELIZATION,
                ORCHESTRATOR_WORKERS, EVALUATOR_OPTIMIZER} <= set(ALL_PATTERNS)

        route = build_pattern(ROUTING, routes={"a": lambda t: "命中A"},
                              classifier=lambda t: "a")
        assert (await route.ainvoke({"task": "T"}))["answer"] == "命中A"

        chain = build_pattern(PROMPT_CHAINING, steps=[lambda t: t + "1", lambda t: t + "2"])
        assert (await chain.ainvoke({"task": "T"}))["answer"] == "T12"

        with pytest.raises(ValueError):
            build_pattern("不存在的模式")


# --------------------------------------------------------------------------
# 3. Agent 通信协议 A2A / ACP / ANP
# --------------------------------------------------------------------------
class TestA2A:
    def test_agent_card_registry_and_discovery(self):
        """Agent Card：注册、技能检索、关键词搜索与去重。"""
        card = AgentCard(
            name="shopping", version="2.1.0", endpoint="local://shopping",
            capabilities=AgentCapabilities(streaming=True),
            skills=[AgentSkill(id="search", name="商品搜索", tags=["商品"])],
        )
        registry = AgentCardRegistry([card])
        assert registry.get("shopping").version == "2.1.0"
        assert [c.name for c in registry.find_by_skill("search")] == ["shopping"]
        assert [c.name for c in registry.search("商品")] == ["shopping"]
        with pytest.raises(ValueError):
            registry.register(card)
        assert registry.unregister("shopping") is True
        assert registry.list() == []

    def test_task_flow_state_transitions(self):
        """任务状态机：提交 -> 执行 -> 完成，非法流转与终态流转被拒绝。"""
        flow = TaskFlow()
        task = flow.submit("shopping", "找耳机")
        assert task.state is TaskState.SUBMITTED
        flow.start(task.id)
        done = flow.complete(task.id, "找到耳机")
        assert done.state is TaskState.COMPLETED
        assert done.history == ["submitted", "working", "completed"]
        with pytest.raises(ValueError):
            flow.start(task.id)  # 终态不可再流转
        fresh = flow.submit("shopping", "另一任务")
        with pytest.raises(ValueError):
            flow.complete(fresh.id, "结果")  # 不能跳过 WORKING

    @pytest.mark.asyncio
    async def test_local_delegator_success_failure_and_async(self):
        """本地委派：handler 成功/异常/异步分别流向 COMPLETED/FAILED/COMPLETED。"""
        registry = AgentCardRegistry([AgentCard(name="worker")])
        delegator = LocalTaskDelegator(registry=registry, handlers={
            "worker": lambda task: f"处理:{task}",
        })
        done = delegator.submit("worker", "T")
        assert done.state is TaskState.COMPLETED and done.result == "处理:T"

        delegator.register_handler("worker", lambda task: 1 / 0)
        failed = delegator.submit("worker", "T")
        assert failed.state is TaskState.FAILED and failed.error

        delegator.register_handler("worker", lambda task: asyncio.sleep(0, result="异步完成"))
        result = await delegator.asubmit("worker", "T")
        assert result.result == "异步完成"


# --------------------------------------------------------------------------
# 4. Tool RAG / 工具动态检索
# --------------------------------------------------------------------------
def _tool(name: str, description: str) -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: "", name=name, description=description
    )


class TestToolRetriever:
    def test_search_ranks_by_relevance(self):
        """Tool RAG：对工具名与描述建索引，中文查询返回最相关工具。"""
        tools = [
            _tool("search_products", "搜索商品，按关键词查找商品"),
            _tool("list_orders", "查询订单列表和订单状态"),
            _tool("initiate_refund", "发起退款申请，处理售后退款"),
        ]
        retriever = ToolRetriever(tools)
        assert retriever.search("查询我的订单", top_k=1)[0].name == "list_orders"
        assert retriever.search("我要退款", top_k=1)[0].name == "initiate_refund"
        hits = retriever.search_with_scores("订单", top_k=2)
        assert len(hits) == 2 and hits[0].score >= hits[1].score
        with pytest.raises(ValueError):
            retriever.search("订单", top_k=0)

    def test_rbac_before_semantic_trimming(self):
        """组合 RBAC：先权限过滤再做语义裁剪，访客拿不到订单工具。"""
        tools = [
            _tool("search_products", "搜索商品"),
            _tool("list_orders", "查询订单列表"),
        ]
        retriever = ToolRetriever(tools)
        guest = User(id="u1", name="访客", role="guest")
        names = [t.name for t in retriever.filtered_search("订单", guest)]
        assert names == ["search_products"]  # 订单工具无权限，即使语义最相关也被剔除

        customer = User(id="u2", name="客户", role="customer")
        names = [t.name for t in retriever.filtered_search("订单", customer)]
        assert names[0] == "list_orders"


# --------------------------------------------------------------------------
# 5. Prompt 版本管理
# --------------------------------------------------------------------------
class TestPromptRegistry:
    def test_versions_render_and_active_switch(self):
        """版本管理：多版本注册、自然排序、活跃版本切换与变量校验。"""
        registry = PromptRegistry()
        registry.register("greet", "v1", "你好 {name}")
        registry.register("greet", "v2", "您好，{name}！")
        registry.register("greet", "v10", "嗨 {name}")
        assert registry.list_versions("greet") == ["v1", "v2", "v10"]
        assert registry.render("greet", name="张三") == "你好 张三"
        registry.set_active("greet", "v10")
        assert registry.render("greet", name="张三") == "嗨 张三"
        assert registry.render("greet", "v2", name="张三") == "您好，张三！"
        with pytest.raises(KeyError):
            registry.set_active("greet", "v99")
        with pytest.raises(KeyError):
            registry.render("greet")  # 缺少模板变量 name

    def test_init_from_personas_and_multimodal_blocks(self):
        """只读初始化 PERSONAS + 多模态 content block 构造。"""
        registry = PromptRegistry()
        assert registry.init_from_personas() >= 4
        persona = registry.render("shopping")
        assert "导购" in persona
        # 再次初始化不重复注册
        assert registry.init_from_personas() == 0

        assert text_block("你好") == {"type": "text", "text": "你好"}
        assert image_url_block("http://x")["image_url"]["url"] == "http://x"
        assert audio_block(b"data")["input_audio"]["format"] == "wav"
        blocks = build_content("说明", images=["http://x"])
        assert [b["type"] for b in blocks] == ["text", "image_url"]
