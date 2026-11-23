"""LangGraph 实现的五类 Agent 编排模式。

每个工厂函数返回编译后的 ``StateGraph``，可直接 ``ainvoke({"task": ...})``。
worker / evaluator 均可注入，全部确定性可断言，不依赖真实模型或网络。
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .models import Evaluation, SubTask, WorkerResult

Worker = Callable[[str], Any]
Evaluator = Callable[[str, str], Any]
Orchestrator = Callable[[str], Any]


def _append(left: Any, right: Any) -> list:
    """LangGraph Annotated reducer：把多节点产出的列表累积起来。"""
    return list(left or []) + list(right or [])


async def _run_workers(workers: Sequence[Worker], inputs: Sequence[str]) -> list[str]:
    """用线程池并发调用同步 worker，并兼容返回协程的异步 worker。"""
    if len(workers) != len(inputs):
        raise ValueError("workers 与 inputs 数量必须一致")
    if not workers:
        return []

    def call(pair: tuple[Worker, str]) -> Any:
        worker, value = pair
        return worker(value)

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        raw = list(pool.map(call, zip(workers, inputs)))

    async def resolve(value: Any) -> str:
        return str(await value if inspect.isawaitable(value) else value)

    return [await resolve(value) for value in raw]


def _as_evaluation(value: Any) -> Evaluation:
    """规范化 evaluator 返回值（Evaluation / dict / 数值 / 元组）。"""
    if isinstance(value, Evaluation):
        return value
    if isinstance(value, dict):
        return Evaluation(**value)
    if isinstance(value, (int, float)):
        return Evaluation(score=float(value))
    if isinstance(value, tuple) and len(value) == 2:
        return Evaluation(score=float(value[0]), feedback=str(value[1]))
    raise TypeError("evaluator 必须返回 Evaluation / dict / 数值 / (score, feedback)")


def _as_subtask(value: Any, index: int) -> SubTask:
    """规范化 orchestrator 返回的子任务（SubTask / dict / 纯文本）。"""
    if isinstance(value, SubTask):
        return value
    if isinstance(value, dict):
        return SubTask(**value)
    return SubTask(id=f"sub{index + 1}", description=str(value))


# --------------------------------------------------------------------------
# 1. Prompt Chaining：顺序链式调用
# --------------------------------------------------------------------------
class ChainState(TypedDict):
    task: str
    outputs: Annotated[list[str], _append]
    answer: str


def prompt_chaining_pattern(steps: Sequence[Worker]) -> Any:
    """Prompt Chaining：把多个步骤顺序串联，前一步输出作为后一步输入。"""
    if not steps:
        raise ValueError("steps 不能为空")

    async def step_node(state: ChainState, index: int, worker: Worker) -> dict[str, Any]:
        value = worker(state["task"] if index == 0 else state["outputs"][-1])
        if inspect.isawaitable(value):
            value = await value
        return {"outputs": [str(value)]}

    builder = StateGraph(ChainState)
    for index, worker in enumerate(steps):
        async def node(state: ChainState, i: int = index, w: Worker = worker) -> dict[str, Any]:
            return await step_node(state, i, w)

        builder.add_node(f"step{index + 1}", node)
    builder.add_edge(START, "step1")
    for index in range(1, len(steps)):
        builder.add_edge(f"step{index}", f"step{index + 1}")

    async def finalize(state: ChainState) -> dict[str, Any]:
        return {"answer": state["outputs"][-1] if state["outputs"] else ""}

    builder.add_node("finalize", finalize)
    builder.add_edge(f"step{len(steps)}", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


# --------------------------------------------------------------------------
# 2. Routing：分类后分发
# --------------------------------------------------------------------------
class RoutingState(TypedDict):
    task: str
    route: str
    answer: str


def routing_pattern(routes: dict[str, Worker], classifier: Callable[[str], str]) -> Any:
    """Routing：先分类任务，再分发给对应 worker。"""
    if not routes:
        raise ValueError("routes 不能为空")

    async def classify(state: RoutingState) -> dict[str, Any]:
        route = classifier(state["task"])
        if inspect.isawaitable(route):
            route = await route
        route = str(route)
        if route not in routes:
            raise ValueError(f"未知路由: {route}")
        return {"route": route}

    async def dispatch(state: RoutingState) -> dict[str, Any]:
        value = routes[state["route"]](state["task"])
        if inspect.isawaitable(value):
            value = await value
        return {"answer": str(value)}

    builder = StateGraph(RoutingState)
    builder.add_node("classify", classify)
    builder.add_node("dispatch", dispatch)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "dispatch")
    builder.add_edge("dispatch", END)
    return builder.compile()


# --------------------------------------------------------------------------
# 3. Parallelization：fan-out 并行 + fan-in 汇总
# --------------------------------------------------------------------------
class ParallelState(TypedDict):
    task: str
    results: Annotated[list[str], _append]
    answer: str


def parallel_pattern(
    workers: Sequence[Worker],
    *,
    aggregator: Callable[[list[str]], Any] | None = None,
) -> Any:
    """Parallelization：并行调用多个 worker，再汇总为一个答案。"""
    if not workers:
        raise ValueError("workers 不能为空")

    async def fan_out(state: ParallelState) -> dict[str, Any]:
        return {"results": await _run_workers(workers, [state["task"]] * len(workers))}

    async def fan_in(state: ParallelState) -> dict[str, Any]:
        results = list(state.get("results", []))
        answer = aggregator(results) if aggregator else "\n".join(results)
        if inspect.isawaitable(answer):
            answer = await answer
        return {"answer": str(answer)}

    builder = StateGraph(ParallelState)
    builder.add_node("fan_out", fan_out)
    builder.add_node("fan_in", fan_in)
    builder.add_edge(START, "fan_out")
    builder.add_edge("fan_out", "fan_in")
    builder.add_edge("fan_in", END)
    return builder.compile()


# --------------------------------------------------------------------------
# 4. Orchestrator-Workers：协调者拆分并动态分发
# --------------------------------------------------------------------------
class OrchestratorState(TypedDict):
    task: str
    subtasks: list[dict[str, Any]]
    results: Annotated[list[dict[str, Any]], _append]
    answer: str


def orchestrator_workers_pattern(
    orchestrator: Orchestrator | None = None,
    workers: dict[str, Worker] | None = None,
    *,
    aggregator: Callable[[list[WorkerResult]], Any] | None = None,
) -> Any:
    """Orchestrator-Workers：协调者拆分任务，按 worker 名称动态分发。

    未提供 orchestrator 时按标点把任务切成句子；未指定 worker 的子任务按
    worker 注册顺序轮询分配。
    """
    worker_map = dict(workers or {})
    if not worker_map:
        raise ValueError("workers 不能为空")
    names = list(worker_map)

    def default_orchestrator(task: str) -> list[dict[str, Any]]:
        parts = [p.strip() for p in task.replace("；", "。").split("。") if p.strip()]
        return [{"id": f"sub{i + 1}", "description": p} for i, p in enumerate(parts)] or [
            {"id": "sub1", "description": task}
        ]

    split_fn = orchestrator or default_orchestrator

    async def orchestrate(state: OrchestratorState) -> dict[str, Any]:
        raw = split_fn(state["task"])
        if inspect.isawaitable(raw):
            raw = await raw
        subtasks = [_as_subtask(item, i).model_dump() for i, item in enumerate(raw)]
        if not subtasks:
            raise ValueError("协调者未拆出任何子任务")
        return {"subtasks": subtasks}

    async def dispatch(state: OrchestratorState) -> dict[str, Any]:
        assignments: list[tuple[Worker, str, str, str]] = []
        for index, item in enumerate(state["subtasks"]):
            subtask = _as_subtask(item, index)
            name = subtask.worker or names[index % len(names)]
            if name not in worker_map:
                raise ValueError(f"未知 worker: {name}")
            assignments.append((worker_map[name], subtask.description, subtask.id, name))

        outputs = await _run_workers([a[0] for a in assignments], [a[1] for a in assignments])
        results = [
            WorkerResult(id=a[2], worker=a[3], output=out).model_dump()
            for a, out in zip(assignments, outputs)
        ]
        return {"results": results}

    async def aggregate(state: OrchestratorState) -> dict[str, Any]:
        records = [WorkerResult(**r) for r in state.get("results", [])]
        answer = aggregator(records) if aggregator else "\n".join(r.output for r in records)
        if inspect.isawaitable(answer):
            answer = await answer
        return {"answer": str(answer)}

    builder = StateGraph(OrchestratorState)
    builder.add_node("orchestrate", orchestrate)
    builder.add_node("dispatch", dispatch)
    builder.add_node("aggregate", aggregate)
    builder.add_edge(START, "orchestrate")
    builder.add_edge("orchestrate", "dispatch")
    builder.add_edge("dispatch", "aggregate")
    builder.add_edge("aggregate", END)
    return builder.compile()


# --------------------------------------------------------------------------
# 5. Evaluator-Optimizer：生成 -> 评估 -> 修订循环
# --------------------------------------------------------------------------
class EvaluatorState(TypedDict):
    task: str
    feedback: str
    score: float
    iterations: int
    _passed: bool
    draft: str
    answer: str
    terminated_reason: str


def evaluator_optimizer_pattern(
    generator: Callable[[str, str], Any],
    evaluator: Evaluator,
    *,
    max_iterations: int = 3,
    score_threshold: float = 0.8,
) -> Any:
    """Evaluator-Optimizer：生成后评估，不达标则带反馈修订，带上限保护。"""
    if max_iterations < 1:
        raise ValueError("max_iterations 必须 >= 1")

    async def generate(state: EvaluatorState) -> dict[str, Any]:
        value = generator(state["task"], state.get("feedback", ""))
        if inspect.isawaitable(value):
            value = await value
        return {"draft": str(value), "iterations": state.get("iterations", 0) + 1}

    async def evaluate(state: EvaluatorState) -> dict[str, Any]:
        raw = evaluator(state["task"], state["draft"])
        if inspect.isawaitable(raw):
            raw = await raw
        result = _as_evaluation(raw)
        return {"score": result.score, "feedback": result.feedback,
                "_passed": result.is_accepted(score_threshold)}

    def route(state: EvaluatorState) -> str:
        if state.get("_passed") or state["score"] >= score_threshold:
            return "finalize"
        if state["iterations"] >= max_iterations:
            return "finalize"
        return "generate"

    async def finalize(state: EvaluatorState) -> dict[str, Any]:
        if state["score"] >= score_threshold:
            reason = "评估达标"
        elif state["iterations"] >= max_iterations:
            reason = f"达到最大迭代次数 {max_iterations}"
        else:
            reason = "循环终止"
        return {"answer": state["draft"], "terminated_reason": reason}

    builder = StateGraph(EvaluatorState)
    builder.add_node("generate", generate)
    builder.add_node("evaluate", evaluate)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "evaluate")
    builder.add_conditional_edges("evaluate", route, {"generate": "generate", "finalize": "finalize"})
    builder.add_edge("finalize", END)
    return builder.compile()
