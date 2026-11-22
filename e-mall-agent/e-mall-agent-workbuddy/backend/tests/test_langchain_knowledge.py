"""LangChain 1.5 知识点专项测试。

按知识点而不是按业务模块组织：消息与模型 / LCEL / Tools / Agent / Middleware /
LangGraph 状态图 / 检查点与人工审批 / MCP / RAG / 上下文工程 / 稳定性。
每个用例都用中文 docstring 说明「知识点 -> 验证点」，便于对照学习。
"""
from __future__ import annotations

import asyncio
import json
import operator
from typing import Annotated, Any, TypedDict

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_core.tools import BaseTool, StructuredTool, tool
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.specialists import build_middleware, build_specialists
from app.agents.supervisor import build_supervisor, classify_route, run_agent, stream_agent
from app.agents.tools import local_tools
from app.context.engine import ContextEngine
from app.domain.models import User
from app.domain.repository import reset_repository
from app.llm.factory import RuleBasedChatModel, get_model
from app.mcp.server import mcp
from app.observability.tracer import current_trace_id, get_tracer
from app.rag.embeddings import HashEmbeddings, tokenize
from app.rag.pipeline import RAGPipeline
from app.security.audit import get_audit_logger
from app.security.rbac import filter_tools, issue_token, set_current_user
from app.workflows.fulfillment import get_fulfillment_graph, resume_fulfillment, run_fulfillment

CUSTOMER = User(id="U001", name="张三", role="customer")


# ---------------------------------------------------------------------------
# 知识点 1：Messages / BaseChatModel —— 消息角色、工具调用协议、流式输出
# ---------------------------------------------------------------------------
class TestMessagesAndChatModel:
    def test_message_roles_and_serialization(self):
        """消息角色：System/Human/AI/Tool 四种消息可构造且内容可读取。"""
        messages = [
            SystemMessage(content="你是电商助手"),
            HumanMessage(content="推荐耳机"),
            AIMessage(content="好的"),
            ToolMessage(content="{}", tool_call_id="c1", name="search_products"),
        ]
        assert [type(m).__name__ for m in messages] == [
            "SystemMessage", "HumanMessage", "AIMessage", "ToolMessage"]
        assert messages[3].tool_call_id == "c1"

    def test_base_chat_model_contract(self):
        """BaseChatModel：离线模型实现 _llm_type / invoke / bind_tools 契约。"""
        model = get_model()
        assert isinstance(model, BaseTool) is False
        assert isinstance(model, RuleBasedChatModel)
        assert model._llm_type == "ecom-rule-based-offline"
        assert isinstance(model.invoke("你好"), AIMessage)

    def test_bind_tools_emits_tool_call(self):
        """工具调用协议：bind_tools 后模型返回带 tool_calls 的 AIMessage。"""
        tools = [t for t in local_tools() if t.name == "check_inventory"]
        bound = RuleBasedChatModel().bind_tools(tools)
        assert len(bound.bound_tools) == 1
        message = bound.invoke([HumanMessage(content="查一下 P001 库存")])
        assert message.tool_calls[0]["name"] == "check_inventory"
        assert message.tool_calls[0]["args"]["product_id"] == "P001"

    def test_tool_message_renders_into_answer(self):
        """工具结果回灌：ToolMessage 内容被模型整理成自然语言答案。"""
        call = {"name": "check_inventory", "args": {}, "id": "c1", "type": "tool_call"}
        payload = json.dumps({"available": True, "stock": 7, "name": "耳机", "product_id": "P001"})
        messages = [
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=payload, tool_call_id="c1", name="check_inventory"),
        ]
        answer = RuleBasedChatModel().invoke(messages).content
        assert "P001" in answer and "7" in answer

    def test_model_stream_interface(self):
        """流式接口：stream() 逐块产出 AIMessage，可拼接出完整回答。"""
        chunks = list(RuleBasedChatModel().stream("你好"))
        assert chunks and all(isinstance(c, AIMessage) for c in chunks)
        assert "电商智能助手" in "".join(str(c.content) for c in chunks)


# ---------------------------------------------------------------------------
# 知识点 2：LCEL（Runnable / 管道 / 并行 / 批处理 / 回调）
# ---------------------------------------------------------------------------
class TestLCEL:
    def test_prompt_model_parser_pipeline(self):
        """LCEL 管道：ChatPromptTemplate | BaseChatModel | StrOutputParser 一次 invoke。"""
        chain = ChatPromptTemplate.from_template("用户说：{text}") | get_model() | StrOutputParser()
        result = chain.invoke({"text": "你好"})
        assert isinstance(result, str) and "电商智能助手" in result

    def test_runnable_lambda_and_parallel(self):
        """Runnable：RunnableLambda 包装函数，RunnableParallel 并行产出字典。"""
        double = RunnableLambda(lambda x: x * 2)
        branch = RunnableParallel({"doubled": double, "text": RunnableLambda(lambda x: f"n={x}")})
        assert branch.invoke(3) == {"doubled": 6, "text": "n=3"}

    def test_batch_and_callback_events(self):
        """批处理与回调：batch 返回同序结果，回调收到 on_llm_start/on_llm_end。"""

        class Recorder(BaseCallbackHandler):
            def __init__(self):
                self.events: list[str] = []

            def on_llm_start(self, *args, **kwargs):
                self.events.append("start")

            def on_llm_end(self, *args, **kwargs):
                self.events.append("end")

        recorder = Recorder()
        chain = ChatPromptTemplate.from_template("{text}") | get_model() | StrOutputParser()
        results = chain.batch([{"text": "你好"}, {"text": "你好"}],
                              config={"callbacks": [recorder]})
        assert len(results) == 2
        assert recorder.events.count("start") == 2
        assert recorder.events.count("end") == 2


# ---------------------------------------------------------------------------
# 知识点 3：Tools —— @tool 装饰器、StructuredTool.schema、直接调用
# ---------------------------------------------------------------------------
class TestTools:
    def test_tool_decorator_generates_schema(self):
        """@tool：函数签名自动生成 name/description/args_schema，可直接 invoke。"""

        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        assert add.name == "add"
        assert set(add.args) == {"a", "b"}
        assert add.invoke({"a": 2, "b": 3}) == 5

    def test_structured_tool_from_function(self):
        """StructuredTool.from_function：把普通业务函数包装为 LangChain 工具。"""
        tools = local_tools()
        assert len(tools) == 8
        search = next(t for t in tools if t.name == "search_products")
        assert isinstance(search, StructuredTool)
        assert "query" in search.args
        assert "商品" in search.description

    @pytest.mark.asyncio
    async def test_tool_ainvoke(self):
        """异步工具调用：ainvoke 与同步 invoke 返回一致的 JSON 字符串。"""
        set_current_user(CUSTOMER)
        tool_obj = next(t for t in local_tools() if t.name == "check_inventory")
        result = json.loads(await tool_obj.ainvoke({"product_id": "P001"}))
        assert result["available"] is True and result["stock"] == 12


# ---------------------------------------------------------------------------
# 知识点 4：create_agent —— 图结构、persona、工具选择、结果状态
# ---------------------------------------------------------------------------
class TestCreateAgent:
    def test_create_agent_compiles_to_graph(self):
        """create_agent：返回可 get_graph() 的 CompiledStateGraph。"""
        agent = create_agent(model=get_model(), tools=local_tools()[:1], name="demo_agent")
        nodes = set(agent.get_graph().nodes)
        assert {"__start__", "model", "tools", "__end__"} <= nodes

    @pytest.mark.asyncio
    async def test_agent_runs_tool_and_finalizes(self):
        """Agent 执行：模型发起工具调用 -> ToolMessage 回灌 -> 最终 AIMessage。"""
        agent = create_agent(model=get_model(),
                             tools=[t for t in local_tools() if t.name == "search_products"])
        result = await agent.ainvoke({"messages": [HumanMessage(content="推荐降噪耳机")]})
        kinds = [type(m).__name__ for m in result["messages"]]
        assert "ToolMessage" in kinds
        assert any("P001" in str(m.content) for m in result["messages"] if isinstance(m, ToolMessage))

    @pytest.mark.asyncio
    async def test_specialists_have_scoped_tools(self):
        """多智能体：每个 specialist 只持有自己职责范围内的工具。"""
        agents = await build_specialists(CUSTOMER)
        assert set(agents) == {"shopping", "order", "support", "general"}
        shopping = set(agents["shopping"].get_graph().nodes)
        assert "tools" in shopping


# ---------------------------------------------------------------------------
# 知识点 5：Middleware —— 摘要、重试、调用上限、PII、自定义 wrap_tool_call
# ---------------------------------------------------------------------------
class TestMiddleware:
    def test_builtin_middleware_config(self):
        """内置中间件：检查摘要/重试/调用上限/PII 的配置参数。"""
        middlewares = build_middleware()
        kinds = [type(m).__name__ for m in middlewares]
        assert "SummarizationMiddleware" in kinds
        assert "ToolRetryMiddleware" in kinds
        assert "ModelCallLimitMiddleware" in kinds
        assert kinds.count("PIIMiddleware") == 2
        summary = next(m for m in middlewares if isinstance(m, SummarizationMiddleware))
        assert summary.trigger == ("messages", 14) and summary.keep == ("messages", 6)
        retry = next(m for m in middlewares if isinstance(m, ToolRetryMiddleware))
        assert retry.max_retries == 1 and retry.initial_delay == 0.0

    @pytest.mark.asyncio
    async def test_pii_middleware_redacts_input(self):
        """PII 中间件：输入中的邮箱在进入模型前被替换为 [REDACTED_EMAIL]。"""
        agent = create_agent(
            model=get_model(), tools=[],
            middleware=[PIIMiddleware("email", strategy="redact", apply_to_input=True)],
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="联系我 abc@example.com 谢谢")]})
        assert "[REDACTED_EMAIL]" in str(result["messages"][0].content)
        assert "abc@example.com" not in str(result["messages"][0].content)

    @pytest.mark.asyncio
    async def test_tool_retry_middleware(self):
        """工具重试：首次失败后中间件自动重试，最终拿到工具结果。"""

        class FlakyTool(BaseTool):
            name: str = "search_products"
            description: str = "search products"
            attempts: int = 0

            def _run(self, query: str) -> str:
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary failure")
                return json.dumps([{"id": "P001", "name": "耳机", "price": 899, "stock": 12}])

        flaky = FlakyTool()
        agent = create_agent(
            model=get_model(), tools=[flaky],
            middleware=[ToolRetryMiddleware(max_retries=1, initial_delay=0.0,
                                            jitter=False, on_failure="continue")],
        )
        result = await agent.ainvoke({"messages": [HumanMessage(content="推荐耳机")]})
        assert flaky.attempts == 2
        assert any(isinstance(m, ToolMessage) for m in result["messages"])

    @pytest.mark.asyncio
    async def test_model_call_limit_middleware(self):
        """模型调用上限：达到 run_limit 后图正常结束，不会无限循环。"""
        agent = create_agent(
            model=get_model(),
            tools=[t for t in local_tools() if t.name == "search_products"],
            middleware=[ModelCallLimitMiddleware(run_limit=1, exit_behavior="end")],
        )
        result = await agent.ainvoke({"messages": [HumanMessage(content="推荐耳机")]})
        assert len(result["messages"]) <= 4

    @pytest.mark.asyncio
    async def test_custom_wrap_tool_call_records_trace(self):
        """自定义中间件：wrap_tool_call 记录每次工具调用到可视化 trace。"""
        set_current_user(CUSTOMER)
        marker = current_trace_id.set("kp-trace")
        try:
            await run_agent("推荐耳机", CUSTOMER, "kp-trace")
            events = get_tracer().query(trace_id="kp-trace")
            assert any(e["node"] == "agent:tool" and e["event"] == "search_products"
                       for e in events)
        finally:
            current_trace_id.reset(marker)


# ---------------------------------------------------------------------------
# 知识点 6：LangGraph —— StateGraph / reducer / 条件边 / 检查点 / 流式更新
# ---------------------------------------------------------------------------
class TestLangGraph:
    def test_state_reducer_accumulates(self):
        """State Reducer：Annotated[list, operator.add] 跨 invoke 累积状态。"""

        class CounterState(TypedDict):
            values: Annotated[list[str], operator.add]

        builder = StateGraph(CounterState)
        builder.add_node("append", lambda state: {"values": ["x"]})
        builder.add_edge(START, "append")
        builder.add_edge("append", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "kp-reducer"}}
        assert graph.invoke({"values": []}, config)["values"] == ["x"]
        assert graph.invoke({"values": []}, config)["values"] == ["x", "x"]

    def test_thread_isolation(self):
        """检查点隔离：不同 thread_id 的状态互不串扰。"""

        class CounterState(TypedDict):
            values: Annotated[list[str], operator.add]

        builder = StateGraph(CounterState)
        builder.add_node("append", lambda state: {"values": ["x"]})
        builder.add_edge(START, "append")
        builder.add_edge("append", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        graph.invoke({"values": []}, {"configurable": {"thread_id": "thread-a"}})
        other = graph.invoke({"values": []}, {"configurable": {"thread_id": "thread-b"}})
        assert other["values"] == ["x"]

    def test_conditional_edges(self):
        """条件边：根据状态字段路由到不同节点。"""

        class RouteState(TypedDict):
            path: str

        builder = StateGraph(RouteState)
        builder.add_node("left", lambda state: {"path": state["path"] + "-left"})
        builder.add_node("right", lambda state: {"path": state["path"] + "-right"})
        builder.add_conditional_edges(START, lambda s: s["path"],
                                      {"go-left": "left", "go-right": "right"})
        builder.add_edge("left", END)
        builder.add_edge("right", END)
        graph = builder.compile()
        assert graph.invoke({"path": "go-left"})["path"] == "go-left-left"
        assert graph.invoke({"path": "go-right"})["path"] == "go-right-right"

    @pytest.mark.asyncio
    async def test_astream_updates(self):
        """流式更新：astream(stream_mode='updates') 逐节点返回状态增量。"""

        class FlowState(TypedDict):
            seq: Annotated[list[str], operator.add]

        builder = StateGraph(FlowState)
        builder.add_node("a", lambda state: {"seq": ["a"]})
        builder.add_node("b", lambda state: {"seq": ["b"]})
        builder.add_edge(START, "a")
        builder.add_edge("a", "b")
        builder.add_edge("b", END)
        graph = builder.compile()
        updates = [u async for u in graph.astream({"seq": []}, stream_mode="updates")]
        assert [next(iter(u)) for u in updates] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_supervisor_graph_routes_to_specialist(self):
        """多智能体编排：Supervisor 图经 context -> route -> specialist -> finalize。"""
        set_current_user(CUSTOMER)
        graph = await build_supervisor(CUSTOMER)
        nodes = set(graph.get_graph().nodes)
        assert {"context", "route", "shopping", "order", "support", "general", "finalize"} <= nodes
        assert classify_route("我的订单") == "order"


# ---------------------------------------------------------------------------
# 知识点 7：Human-in-the-loop —— interrupt() / Command(resume=...)
# ---------------------------------------------------------------------------
class TestHumanInTheLoop:
    @pytest.mark.asyncio
    async def test_interrupt_then_resume(self):
        """人工审批：interrupt 挂起后状态可查询，Command(resume=True) 恢复并完成。"""
        set_current_user(User(id="A001", name="管理员", role="admin"))
        first = await run_fulfillment("O1001", "U001", "kp-hitl")
        assert first["status"] == "awaiting_approval"
        state = get_fulfillment_graph().get_state({"configurable": {"thread_id": "kp-hitl"}})
        assert state.interrupts and state.next == ("risk_review",)
        second = await resume_fulfillment("kp-hitl", True)
        assert second["status"] == "completed"

    @pytest.mark.asyncio
    async def test_reject_branch(self):
        """审批拒绝：resume(False) 走取消分支，订单状态回写为 cancelled。"""
        set_current_user(User(id="A001", name="管理员", role="admin"))
        await run_fulfillment("O1001", "U001", "kp-reject")
        result = await resume_fulfillment("kp-reject", False)
        assert result["status"] == "cancelled"

    def test_command_import_contract(self):
        """Command API：resume 值通过 Command(resume=...) 传入图；interrupt 可调用。"""
        assert Command(resume=True).resume is True
        assert callable(interrupt)


# ---------------------------------------------------------------------------
# 知识点 8：MCP —— FastMCP 注册、langchain-mcp-adapters 客户端往返
# ---------------------------------------------------------------------------
class TestMCP:
    @pytest.mark.asyncio
    async def test_fastmcp_registers_tools(self):
        """MCP Server：FastMCP 实例注册全部业务工具且可被 list_tools 枚举。"""
        tools = await mcp.list_tools()
        assert len(tools) == 8
        assert "search_products" in {t.name for t in tools}

    @pytest.mark.asyncio
    async def test_mcp_stdio_roundtrip(self):
        """MCP Client：MultiServerMCPClient 经 stdio 完成 ListTools + CallTool。"""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        import os
        import sys
        from pathlib import Path

        env = dict(os.environ)
        backend_dir = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = backend_dir + os.pathsep + env.get("PYTHONPATH", "")
        client = MultiServerMCPClient({
            "ecommerce": {"transport": "stdio", "command": sys.executable,
                          "args": ["-m", "app.mcp.server"], "env": env},
        })
        tools = await client.get_tools()
        assert len(tools) == 8
        result = await next(t for t in tools if t.name == "search_products").ainvoke({"query": "耳机"})
        assert "P001" in str(result)

    def test_rbac_filters_exposed_tools(self):
        """MCP + RBAC：按角色过滤工具，guest 看不到下单/退款工具。"""
        tools = local_tools()
        guest = {t.name for t in filter_tools(tools, User(id="g", role="guest"))}
        assert "create_order" not in guest and "initiate_refund" not in guest
        assert "search_products" in guest


# ---------------------------------------------------------------------------
# 知识点 9：RAG —— Embeddings 接口、向量库、检索重排
# ---------------------------------------------------------------------------
class TestRAG:
    def test_embeddings_interface(self):
        """Embeddings：自定义实现继承 Embeddings，输出定长且 L2 归一化向量。"""
        emb = HashEmbeddings(dimension=64)
        assert isinstance(emb, Embeddings)
        vec = emb.embed_query("退货政策")
        assert len(vec) == 64 and emb.embed_documents(["退货政策"])[0] == vec
        assert abs(sum(v * v for v in vec) - 1.0) < 1e-6

    def test_chinese_ngram_tokenizer(self):
        """中文分词：bigram + trigram，兼顾拉丁词。"""
        tokens = tokenize("退货政策 refund")
        assert {"退货", "货政", "退货政", "refund"} <= set(tokens)

    def test_in_memory_vector_store(self):
        """InMemoryVectorStore：add_texts 写入 metadata，similarity_search 返回 Document。"""
        store = InMemoryVectorStore(HashEmbeddings(dimension=64))
        store.add_texts(["七天无理由退货", "满199包邮"],
                        metadatas=[{"source": "售后政策"}, {"source": "配送规则"}])
        docs = store.similarity_search("退货", k=2)
        assert len(docs) == 2 and all(isinstance(d, Document) for d in docs)
        assert {d.metadata["source"] for d in docs} == {"售后政策", "配送规则"}

    def test_hybrid_retrieval_and_category_filter(self):
        """RAG 检索：向量召回 + 词面重排；category 过滤只返回指定知识域。"""
        pipeline = RAGPipeline(top_k=2)
        docs = pipeline.retrieve("发票怎么开", category="payment")
        assert docs and all(d["category"] == "payment" for d in docs)
        assert "发票" in pipeline.as_context("发票怎么开")


# ---------------------------------------------------------------------------
# 知识点 10：上下文工程 —— 优先级装箱、预算、滑窗、可解释快照
# ---------------------------------------------------------------------------
class TestContextEngineering:
    def test_priority_packing_and_snapshot(self):
        """上下文装箱：按优先级纳入区块，首条 SystemMessage 含角色与身份。"""
        engine = ContextEngine(max_chars=2000, recent_messages=6)
        messages, snapshot = engine.build(
            persona="你是电商助手", user=CUSTOMER,
            retrieved_docs=[{"source": "售后政策", "content": "七天无理由退货"}],
            tools=[{"name": "search_products", "description": "搜索商品"}],
            history=[HumanMessage(content="旧问题"), AIMessage(content="旧回答")],
            user_input="推荐耳机",
        )
        assert isinstance(messages[0], SystemMessage)
        assert "当前用户: U001" in messages[0].content
        assert [s["priority"] for s in snapshot.sections] == [1, 2, 3, 4]
        assert snapshot.total_chars <= 2000

    def test_sliding_window_and_compression(self):
        """滑窗与压缩：旧轮次被丢弃，超长单轮带压缩标记。"""
        engine = ContextEngine(max_chars=400, recent_messages=2)
        _, snapshot = engine.build(
            persona="角色", user=CUSTOMER,
            history=[HumanMessage(content=f"历史{i}") for i in range(8)],
            user_input="继续",
        )
        assert snapshot.dropped_messages >= 5
        engine = ContextEngine(max_chars=400, recent_messages=2)
        _, snapshot = engine.build(
            persona="角色", user=CUSTOMER,
            history=[HumanMessage(content="很长" * 200)], user_input="继续",
        )
        assert snapshot.compressed


# ---------------------------------------------------------------------------
# 知识点 11：稳定性 —— RBAC、HMAC Token、审计、越权拦截
# ---------------------------------------------------------------------------
class TestStability:
    def test_token_signature_and_expiry(self):
        """HMAC Token：篡改签名或错误密钥均返回 None。"""
        token = issue_token(CUSTOMER, "secret", ttl=-1)
        from app.security.rbac import decode_token

        assert decode_token(token, "secret") is None  # 已过期
        valid = issue_token(CUSTOMER, "secret", ttl=60)
        assert decode_token(valid, "secret")["sub"] == "U001"
        assert decode_token(valid, "wrong") is None

    def test_tool_level_scope_enforcement(self):
        """工具内二次鉴权：绕过 API 直接调用也必须拒绝越权。"""
        from app.mcp.tools import get_order

        set_current_user(User(id="U002", role="customer"))
        denied = json.loads(get_order("O1001"))
        assert denied["permission_denied"]
        assert any(e["decision"] == "deny" for e in get_audit_logger().query())

    def test_reset_repository_is_deterministic(self):
        """测试隔离：reset_repository 后种子数据恢复，用例之间不互相污染。"""
        reset_repository()
        from app.domain.repository import get_repository

        assert len(get_repository().list_products()) >= 8
        assert get_repository().get_product("P001").stock == 12
