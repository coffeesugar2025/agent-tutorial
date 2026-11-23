"""Sandbox / Code Mode / Harness / checkpoint-resume 测试。"""
from __future__ import annotations

import time

import pytest

from app.resume import (
    CheckpointStore,
    InMemoryCheckpointStore,
    ResumableRunner,
    ResumeLimitExceeded,
    TaskCheckpoint,
)
from app.sandbox import (
    CodeModeRunner,
    CodeSandbox,
    Harness,
    HarnessBudgetExceeded,
    SandboxPolicy,
    build_tool_namespace,
)


# --------------------------------------------------------------- CodeSandbox
def test_safe_code_executes_and_returns_last_expression():
    result = CodeSandbox().run(
        "values = [x * x for x in range(5)]\nprint(sum(values))\nsum(values)"
    )
    assert result.ok, result.error
    assert result.value == 30
    assert result.stdout.strip() == "30"
    assert result.duration_ms >= 0


def test_result_variable_is_returned():
    result = CodeSandbox().run("result = {'ok': True, 'n': 3}")
    assert result.ok, result.error
    assert result.value == {"ok": True, "n": 3}


@pytest.mark.parametrize("module", ["os", "subprocess", "socket", "sys", "pathlib"])
def test_dangerous_import_is_rejected(module):
    result = CodeSandbox().run(f"import {module}")
    assert not result.ok
    assert "禁止导入模块" in result.error
    assert result.stdout == ""


def test_import_from_dangerous_module_is_rejected():
    result = CodeSandbox().run("from os import path")
    assert not result.ok
    assert "禁止导入模块" in result.error


@pytest.mark.parametrize("attr", ["__class__", "__globals__", "__builtins__",
                                  "__subclasses__"])
def test_dangerous_attribute_is_rejected(attr):
    result = CodeSandbox().run(f"x = (1).{attr}")
    assert not result.ok
    assert "禁止访问属性" in result.error


def test_object_escape_chain_is_rejected():
    code = "x = ().__class__.__mro__[1].__subclasses__()"
    result = CodeSandbox().run(code)
    assert not result.ok
    assert "禁止访问属性" in result.error


@pytest.mark.parametrize("call", ["eval", "exec", "compile", "open", "__import__"])
def test_dangerous_calls_are_rejected(call):
    result = CodeSandbox().run(f"{call}('1+1')")
    assert not result.ok
    assert ("禁止使用名称" in result.error or "禁止调用函数" in result.error)


def test_getattr_escape_is_rejected():
    result = CodeSandbox().run("getattr(1, '__class__')")
    assert not result.ok


def test_timeout_stops_infinite_loop():
    policy = SandboxPolicy(timeout_ms=20, max_steps=10_000_000)
    result = CodeSandbox(policy).run("while True:\n    pass")
    assert not result.ok
    assert "超时" in result.error


def test_max_steps_enforced():
    policy = SandboxPolicy(timeout_ms=5000, max_steps=50)
    result = CodeSandbox(policy).run("for i in range(1000):\n    x = i")
    assert not result.ok
    assert "步数" in result.error


def test_output_is_truncated_to_policy_limit():
    policy = SandboxPolicy(max_output_length=8)
    result = CodeSandbox(policy).run("print('abcdefghijklmnop')")
    assert result.ok, result.error
    assert result.stdout == "abcdefgh"


def test_syntax_error_is_reported_without_raising():
    result = CodeSandbox().run("def broken(:")
    assert not result.ok
    assert "语法错误" in result.error


# ---------------------------------------------------------------- Code Mode
def test_build_tool_namespace_from_mapping_and_callables():
    ns = build_tool_namespace({"double": lambda x: x * 2})
    assert ns.names() == ["double"]
    assert ns.double(4) == 8

    def triple(x):
        return x * 3

    ns2 = build_tool_namespace([triple])
    assert ns2.names() == ["triple"]
    assert ns2.triple(3) == 9


def test_code_mode_orchestrates_tools_via_attribute_access():
    runner = CodeModeRunner()
    ns = runner.build_tool_namespace({
        "search_products": lambda q: [{"id": "P1", "q": q}],
        "check_inventory": lambda pid: {"id": pid, "stock": 7},
    })
    code = (
        "items = tools.search_products('手机')\n"
        "stock = tools.check_inventory(items[0]['id'])\n"
        "result = {'item': items[0], 'stock': stock['stock']}"
    )
    result = runner.run(code, ns)
    assert result.ok, result.error
    assert result.value == {"item": {"id": "P1", "q": "手机"}, "stock": 7}
    assert [c.name for c in ns.calls] == ["search_products", "check_inventory"]


def test_code_mode_records_failed_tool_call():
    def broken():
        raise ValueError("boom")

    ns = build_tool_namespace({"broken": broken})
    runner = CodeModeRunner()
    result = runner.run("tools.broken()", ns)
    assert not result.ok
    assert "boom" in result.error
    assert ns.calls[0].ok is False
    assert "boom" in ns.calls[0].error


def test_code_mode_blocks_dangerous_generated_code():
    runner = CodeModeRunner()
    result = runner.run("import os\nos.system('echo hacked')",
                        runner.build_tool_namespace({}))
    assert not result.ok
    assert "禁止导入模块" in result.error


# ------------------------------------------------------------------- Harness
def test_harness_records_tool_and_code_calls_and_builds_report():
    with Harness(trace_id="trace-1", user="u-1",
                 tool_namespace={"double": lambda x: x * 2}) as harness:
        assert harness.call_tool("double", 5) == 10
        result = harness.run_code("result = tools.double(3)")
        assert result.ok, result.error
        harness.record("custom_event", {"k": "v"}, output="done")

    report = harness.close()
    assert report["trace_id"] == "trace-1"
    assert report["user"] == "u-1"
    assert report["call_count"] == 3
    assert report["success_rate"] == 1.0
    assert [c["kind"] for c in report["calls"]] == ["tool", "code", "event"]
    assert report["deadline_exceeded"] is False


def test_harness_enforces_tool_call_budget():
    harness = Harness(tool_namespace={"ping": lambda: "pong"},
                      budget={"max_tool_calls": 1})
    assert harness.call_tool("ping") == "pong"
    with pytest.raises(HarnessBudgetExceeded):
        harness.call_tool("ping")


def test_harness_deadline_is_enforced():
    # 注入可控单调时钟：避免 Windows 上 time.monotonic() ~15ms 分辨率导致
    # sleep(0.003) 不一定推进时钟的偶发失败（生产默认仍用 time.monotonic）。
    now = [1000.0]
    harness = Harness(tool_namespace={"ping": lambda: "pong"}, deadline=0.001,
                      clock=lambda: now[0])
    now[0] += 0.01
    with pytest.raises(HarnessBudgetExceeded):
        harness.call_tool("ping")
    report = harness.close()
    assert report["deadline_exceeded"] is True


# ---------------------------------------------------------------- Checkpoint
def test_checkpoint_save_load_list_and_delete():
    store = InMemoryCheckpointStore()
    store.save(TaskCheckpoint("task-a", 0, {"n": 1}))
    store.save(TaskCheckpoint("task-a", 1, {"n": 2}))
    store.save(TaskCheckpoint("task-b", 0, {"n": 9}))

    assert store.load("task-a").step_index == 1
    assert store.load("task-a", 0).state == {"n": 1}
    assert len(store.list("task-a")) == 2
    assert len(store.list()) == 3

    store.delete("task-a")
    assert store.load("task-a") is None
    assert store.list("task-a") == []


def test_checkpoint_hash_detects_state_tampering():
    cp = TaskCheckpoint("task", 0, {"a": 1, "b": 2})
    assert cp.valid
    original = cp.hash
    cp.state["a"] = 999
    assert not cp.valid
    assert cp.hash == original


def test_checkpoint_dict_roundtrip_preserves_hash():
    cp = TaskCheckpoint("task", 3, {"x": [1, 2]})
    restored = TaskCheckpoint.from_dict(cp.to_dict())
    assert restored == cp
    assert restored.valid


def test_in_memory_store_satisfies_checkpoint_store_protocol():
    assert isinstance(InMemoryCheckpointStore(), CheckpointStore)


# ------------------------------------------------------------- ResumableRunner
async def _make_steps(log):
    async def first(state, ctx):
        log.append(("first", ctx.step_index))
        state["items"] = ["first"]
        return state

    async def second(state, ctx):
        log.append(("second", ctx.step_index))
        state["items"].append("second")
        return state

    async def third(state, ctx):
        log.append(("third", ctx.step_index))
        state["items"].append("third")
        return state

    return [first, second, third]


async def test_resumable_runner_completes_all_steps():
    log = []
    runner = ResumableRunner(await _make_steps(log))
    result = await runner.run("task-1")
    assert result["completed"] is True
    assert result["state"]["items"] == ["first", "second", "third"]
    assert [name for name, _ in log] == ["first", "second", "third"]


async def test_resumable_runner_interrupts_then_resumes_from_checkpoint():
    log = []
    runner = ResumableRunner(await _make_steps(log))
    first = await runner.run("task-2", stop_after=0)
    assert first["interrupted"] is True
    assert first["state"]["items"] == ["first"]

    resumed = await runner.resume("task-2")
    assert resumed["completed"] is True
    assert resumed["state"]["items"] == ["first", "second", "third"]
    assert [name for name, _ in log] == ["first", "second", "third"]
    assert runner.resume_counts == {"task-2": 1}


async def test_idempotent_steps_are_not_repeated_on_replay():
    log = []
    runner = ResumableRunner(await _make_steps(log))
    await runner.run("task-3", stop_after=0)
    result = await runner.resume("task-3", from_step=0)
    assert result["state"]["items"] == ["first", "second", "third"]
    assert [name for name, _ in log] == ["first", "second", "third"]


async def test_non_idempotent_step_can_be_replayed():
    log = []

    async def step(state, ctx):
        log.append(ctx.step_index)
        state["count"] = state.get("count", 0) + 1
        return state

    from app.resume import Step
    # 用独立 store + 显式 checkpoint 模拟重放场景
    store = InMemoryCheckpointStore()
    store.save(TaskCheckpoint("task-4b", 0, {"count": 1}))
    replay = ResumableRunner([Step("step", step, idempotent=False)], store=store)
    replay._completed.add(("task-4b", 0))
    out = await replay.resume("task-4b", from_step=0)
    assert out["state"]["count"] == 2


async def test_resume_limit_exceeded():
    log = []
    runner = ResumableRunner(await _make_steps(log), max_resumes=1)
    await runner.run("task-5", stop_after=0)
    await runner.resume("task-5", stop_after=1)
    with pytest.raises(ResumeLimitExceeded):
        await runner.resume("task-5")


async def test_resume_without_checkpoint_raises_key_error():
    runner = ResumableRunner([])
    with pytest.raises(KeyError):
        await runner.resume("missing-task")
