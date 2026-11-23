# 新增能力快速上手

本文档给出能力图谱补齐部分的调用示例。所有示例零 API Key 可运行，代码位于 `backend/`。

## 1. Planning / ReAct / Plan-and-Solve

```python
import asyncio
from app.planning import create_planning_graph, ReActLoop, PlanAndSolvePlanner
from app.domain.models import User

async def main():
    user = User(id="U001", name="张三", role="customer")

    # 统一图入口：mode 可选 react / plan_solve
    graph = create_planning_graph(mode="plan_solve")
    result = await graph.ainvoke({"goal": "查询P001库存并下单1件", "user": user.model_dump()})
    print(result["answer"], result["trace"], result["terminated_reason"])

    # 单独使用规划器
    plan = await PlanAndSolvePlanner().aplan("查库存并下单", user)
    print([s.description for s in plan.steps])

asyncio.run(main())
```

`ReActLoop` 以 Thought → Action → Observation 循环运行，用 `max_steps` 与重复动作检测终止。

## 2. 错误恢复 / 重试 / 幂等 / 超时 / 降级

```python
from app.reliability import (
    ResilienceConfig, RetryPolicy, TimeoutPolicy,
    IdempotencyGuard, StopConditions,
)

config = ResilienceConfig(
    retry=RetryPolicy(max_attempts=3, base_delay=0.05),
    timeout=TimeoutPolicy(seconds=2.0, fallback="timeout-fallback"),
    idempotency=IdempotencyGuard(),
    stop=StopConditions(max_steps=10),
)
result = asyncio.run(config.run("order-create-key", lambda: "done", fallback="degraded"))
```

执行顺序：幂等 → 终止条件 → 超时 → 重试 → 降级。

## 3. 三层记忆

```python
from app.memory import MemoryManager, InMemoryMemoryStore

manager = MemoryManager(InMemoryMemoryStore())
manager.remember("U001", "thread-1", "推荐耳机", "P001 ¥899",
                 goal="选购耳机", outcome="已推荐P001", tags=["导购"])
manager.user.upsert_preference("U001", "color", "黑色", confidence=0.9)
manager.user.add_fact("U001", "对镍过敏", source="历史订单备注")

recall = manager.recall("U001", "thread-1", "耳机")
print(recall.injected_context, recall.token_estimate)
manager.forget_user("U001")  # 合规删除
```

跨用户隔离：`U001` 永远读不到 `U002` 的记忆。

## 4. 混合检索 / 知识治理 / 幻觉控制

```python
from app.rag.hybrid import HybridRetriever
from app.rag.citation import CitationValidator, GroundednessScorer
from app.rag.governance import VersionedStore

retriever = HybridRetriever([
    {"id": "p1", "content": "退款7个工作日到账", "metadata": {"category": "policy"}}
])
chunks = retriever.search("退款多久到账", top_k=3)
print([(c.rank, c.score, c.sources.keys()) for c in chunks])

report = CitationValidator(chunks).validate("退款7天到账 [1]")
grounded = GroundednessScorer(chunks).score("退款7天到账")
print(report.invalid_markers(), grounded.score)

store = VersionedStore()
store.ingest("policy-1", [{"content": "v1 内容", "metadata": {}}])
store.ingest("policy-1", [{"content": "v2 内容", "metadata": {}}])
store.rollback("policy-1", 1)
```

## 5. Text2SQL / Text2Cypher / GraphRAG

```python
from app.rag.text2sql import Text2SQL, Text2Cypher, create_demo_db
from app.rag.graphrag import GraphRAGRetriever

result = Text2SQL(create_demo_db()).run("列出价格低于500的商品")
print(result.sql, result.as_dicts())

query = Text2Cypher().generate("查订单O1001的商品")
print(query.cypher, query.params)

retriever = GraphRAGRetriever()
retriever.build([{"content": "售后政策包含退款规则", "metadata": {"category": "policy"}}])
print(retriever.retrieve("退款", hops=1).description)
```

`Text2SQL.generate` 只产出白名单 SELECT，禁止 DML 且自动加 LIMIT，注入语句会被 `validate_select` 拒绝。

## 6. Sandbox / Code Mode / Harness

```python
from app.sandbox import CodeSandbox, CodeModeRunner, Harness
from app.agents.tools import local_tools

print(CodeSandbox().run("print(6*7)").stdout)        # 42
print(CodeSandbox().run("import os").ok)             # False，AST 拦截

runner = CodeModeRunner()
result = runner.run(
    "print(tools.search_products(query='耳机'))",
    tools=local_tools(),
)
print(result.ok)

with Harness(trace_id="task-1") as h:
    h.call_tool("search_products", query="耳机")
print(h.close())
```

## 7. 长任务恢复

```python
from app.resume import InMemoryCheckpointStore, ResumableRunner

async def fail_once(state, ctx):
    if ctx.step_index == 1:
        raise RuntimeError("中断")
    return "ok"

runner = ResumableRunner([lambda s: "a", fail_once, lambda s: "c"],
                         store=InMemoryCheckpointStore())
await runner.run("task-1")           # 第 2 步中断
await runner.resume("task-1")        # 从第 2 步继续，第 1 步不重复
```

## 8. Metrics / 评测 / 回归门禁

```python
from app.observability.metrics import MetricsCollector
from app.eval import CaseDataset, GoldenCase, Evaluator, ReplayRunner, RegressionGate

metrics = MetricsCollector()
metrics.record_agent_run("shopping", True, 42.0, tokens=100, tools_used=["search_products"])
print(metrics.snapshot()["summary"])   # 含 P50/P95/P99

dataset = CaseDataset([
    GoldenCase(id="c1", input="推荐耳机", expected={"type": "contains", "value": "P001"}, tags=["导购"])
])
report = asyncio.run(Evaluator().evaluate(dataset, lambda case: {"answer": "P001 ¥899"}))
print(report.pass_rate, report.p95_latency_ms)

gate = RegressionGate().check(baseline_report, report)
print(gate.passed)
```

## 9. HTTP 端点速查

| 能力 | 端点 |
|---|---|
| 规划 | `POST /api/capabilities/plan` |
| 混合检索 | `POST /api/capabilities/rag/hybrid` |
| Text2SQL | `POST /api/capabilities/rag/text2sql` |
| Text2Cypher | `GET /api/capabilities/rag/text2cypher` |
| GraphRAG | `POST /api/capabilities/rag/graph` |
| 引用/幻觉 | `POST /api/capabilities/rag/citation` |
| 记忆召回/写入/删除 | `GET/POST /api/capabilities/memory`、`DELETE /api/capabilities/memory/{user_id}` |
| 代码沙箱 | `POST /api/capabilities/sandbox` |
| 指标快照 | `GET /api/capabilities/metrics` |
| 批量评测 | `POST /api/capabilities/eval` |

详细请求体见 `docs/API.md`；前端"能力实验室"页（`http://localhost:5173/lab`）可交互体验全部能力。
