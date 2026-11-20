"""第 14 章：Sandbox、Code Mode 与长任务恢复（LangChain 版）。

保留 AST 白名单、子进程超时、50 份简历 JSON checkpoint；用 @tool 包装
safe_eval 与沙箱执行，用 create_agent 演示 Code Mode；长任务仍用 JSON
checkpoint（InMemorySaver 存图状态，批量任务建议业务侧 checkpoint）。
运行：python code/ch14_sandbox.py
"""
from __future__ import annotations
import ast
import json
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from langchain.agents import create_agent
from langchain_core.tools import tool
from common.data import candidates
from common.lc import MockChatModel, final_text, tool_names

ALLOWED_CALLS = {"sum", "len", "min", "max"}
BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
CMP_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
SAFE_GLOBALS = {"__builtins__": {}, "sum": sum, "len": len, "min": min, "max": max}

class UnsafeCode(ValueError):
    """代码没有通过白名单。"""

def _check(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        _check(node.body)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool, type(None))):
            raise UnsafeCode(f"不允许的常量类型：{type(node.value).__name__}")
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, BIN_OPS):
            raise UnsafeCode("只允许 + - * / 四则运算")
        _check(node.left); _check(node.right)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise UnsafeCode("只允许正负号")
        _check(node.operand)
    elif isinstance(node, ast.Compare):
        if not all(isinstance(op, CMP_OPS) for op in node.ops):
            raise UnsafeCode("只允许 == != < <= > >=")
        _check(node.left)
        for comparator in node.comparators: _check(comparator)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            _check(element)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            raise UnsafeCode(f"只允许调用 {sorted(ALLOWED_CALLS)}")
        if node.keywords:
            raise UnsafeCode("不允许关键字参数")
        for argument in node.args: _check(argument)
    else:
        raise UnsafeCode(f"禁止的语法：{type(node).__name__}")

def safe_eval(expression: str):
    tree = ast.parse(expression, mode="eval")
    _check(tree)
    return eval(compile(tree, "<safe_eval>", "eval"), SAFE_GLOBALS, {})  # noqa: S307 - 已通过白名单

def run_in_subprocess(code: str, timeout: float = 0.4) -> dict:
    with tempfile.TemporaryDirectory(prefix="ch14_sub_") as tmp:
        script = Path(tmp) / "job.py"
        script.write_text(code, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "", "timed_out": True}
        return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "timed_out": False}
@dataclass

class LongTask:
    items: list[dict]
    checkpoint: Path
    batch_size: int = 10
    def __post_init__(self) -> None:
        self.results: dict[str, dict] = {}
        self.next_index = 0
        self.work_log: list[str] = []
    def _save(self) -> None:
        payload = {"next_index": self.next_index, "results": [self.results[key] for key in sorted(self.results)]}
        self.checkpoint.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    def _load(self) -> None:
        if not self.checkpoint.exists():
            return
        payload = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        self.next_index = payload["next_index"]
        self.results = {row["id"]: row for row in payload["results"]}
    def _process(self, item: dict) -> dict:
        return {"id": item["id"], "level": "senior" if item["years"] >= 5 else "junior", "skills": item["skills"]}
    def run(self, fail_at: int | None = None) -> None:
        self._load()
        for index in range(self.next_index, len(self.items)):
            if fail_at is not None and index == fail_at:
                raise RuntimeError(f"进程在第 {index + 1} 份简历前被杀死")
            item = self.items[index]
            self.results[item["id"]] = self._process(item)  # 以 id 为键，天然幂等
            self.work_log.append(item["id"])
            self.next_index = index + 1
            if self.next_index % self.batch_size == 0:
                self._save()
        self._save()
    def resume(self) -> int:
        self.run()
        return len(self.results)

def make_resumes(count: int = 50) -> list[dict]:
    base = candidates()
    return [{"id": f"R{index + 1:03d}", "name": base[index % len(base)]["name"], "years": base[index % len(base)]["years"],
             "skills": list(base[index % len(base)]["skills"])} for index in range(count)]

MODEL_AGGREGATE_CODE = """result = {}
for resume in data:
    for skill in resume["skills"]:
        if skill in result:
            result[skill] = result[skill] + 1
        else:
            result[skill] = 1
"""

EVIL_AGGREGATE_CODE = """import os
result = {}
os.system("echo pwned")
"""

AGGREGATE_NODES = (
    ast.Module, ast.Assign, ast.For, ast.If, ast.Name, ast.Constant, ast.Subscript,
    ast.BinOp, ast.Add, ast.Sub, ast.Compare, ast.In, ast.NotIn, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Load, ast.Store, ast.List, ast.Tuple,
    ast.Dict, ast.And, ast.Or, ast.Not, ast.UnaryOp, ast.USub,
)

def validate_aggregate(code: str) -> None:
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if not isinstance(node, AGGREGATE_NODES):
            raise UnsafeCode(f"聚合代码包含禁止节点：{type(node).__name__}")
@tool

def safe_calc(expression: str) -> str:
    """计算只含常量、四则、比较与 sum/len/min/max 的表达式，例如 (12000-8000)/3。"""
    return str(safe_eval(expression))

def make_aggregate_tool(data: list[dict]):
    @tool
    def run_aggregate_code(code: str) -> str:
        """在 AST 白名单和子进程中执行聚合代码，返回 JSON 字符串。代码必须给 result 赋值。"""
        validate_aggregate(code)
        payload = json.dumps(data, ensure_ascii=False)
        program = f"import json\ndata = json.loads({payload!r})\n{code}\nprint(json.dumps(result, ensure_ascii=True))\n"
        outcome = run_in_subprocess(program, timeout=3.0)
        if not outcome["ok"]:
            raise RuntimeError(outcome["stderr"] or "子进程执行失败")
        return outcome["stdout"]
    return run_aggregate_code

def run_code_mode(data: list[dict]) -> dict:
    """模型只写代码，工具负责校验 + 隔离执行，结果以 ToolMessage 回填。"""
    aggregate_tool = make_aggregate_tool(data)
    model = MockChatModel(script=[
        {"tool_calls": [{"name": "run_aggregate_code", "args": {"code": MODEL_AGGREGATE_CODE}}]}, {"content": "聚合完成，技能分布已由工具回填。"}])
    agent = create_agent(model=model, tools=[aggregate_tool], system_prompt="你是数据分析助手；批量聚合时写 Python 代码并调用工具。")
    state = agent.invoke({"messages": [{"role": "user", "content": "统计 50 份简历的技能分布，用代码一次算完。"}]})
    return state

def main() -> None:
    print("=== 1. safe_eval 与 @tool 包装 ===")
    print(f"@tool {safe_calc.name}：{safe_calc.invoke({'expression': '(12000 - 8000) / 3'})}；允许 sum/len：{safe_eval('sum([1, 2, 3]) + len((4, 5))')}")
    assert safe_eval("min(3, 5) * max(2, 4)") == 12 and safe_eval("2 + 3 * 4") == 14
    print("\n=== 2. 攻击样例：全部被 AST 白名单拒绝 ===")
    attacks = [
        "__import__('os').system('echo hacked')",
        "open('secret.txt').read()",
        "'abc'.upper()",
        "[1, 2, 3][0]",
        "(lambda: 1)()",
        "sum([x for x in (1, 2)])",
        "1 ** 999999",
        "1 if True else 2",
    ]
    for attack in attacks:
        try:
            safe_eval(attack)
        except UnsafeCode as exc:
            print(f"  拒绝 {attack[:34]!r:<38} -> {exc}")
        else:
            raise AssertionError(f"没有拦住：{attack}")
    try:
        safe_calc.invoke({"expression": "open('secret.txt')"})
    except Exception as exc:  # noqa: BLE001 - 工具层同样拒绝
        print(f"  @tool 层同样拒绝：{type(exc).__name__}: {exc}")
    print("\n=== 3. 子进程隔离：超时直接杀进程 ===")
    normal = run_in_subprocess("print(6 * 7)", timeout=2.0)
    killed = run_in_subprocess("print('start', flush=True)\nwhile True:\n    pass\n", timeout=0.4)
    print(f"正常代码：ok={normal['ok']} stdout={normal['stdout']!r}；死循环：timed_out={killed['timed_out']}")
    assert normal["ok"] and normal["stdout"] == "42" and killed["timed_out"]
    print("\n=== 4. 长任务：50 份简历，JSON checkpoint，第 23 份中断 ===")
    with tempfile.TemporaryDirectory(prefix="ch14_") as tmp:
        checkpoint = Path(tmp) / "resume_checkpoint.json"
        task = LongTask(make_resumes(50), checkpoint)
        try:
            task.run(fail_at=22)
        except RuntimeError as exc:
            print(f"崩溃：{exc}")
        print(f"崩溃时内存 {len(task.results)} 条、磁盘 checkpoint {json.loads(checkpoint.read_text(encoding='utf-8'))['next_index']} 条")
        resumed = LongTask(task.items, checkpoint)
        total = resumed.resume()
        print(f"恢复完成：{total} 条；从 {resumed.work_log[0]} 开始，处理 {len(resumed.work_log)} 条（R021/R022 重做，按 id 幂等）")
        counts = Counter(skill for row in resumed.results.values() for skill in row["skills"])
        expected = Counter(skill for item in task.items for skill in item["skills"])
        assert total == 50 and len({row["id"] for row in resumed.results.values()}) == 50
        assert resumed.work_log[0] == "R021" and len(resumed.work_log) == len(set(resumed.work_log)) and counts == expected
        print("\n=== 5. Code Mode：模型生成代码 → @tool 沙箱执行 → 结果回填 ===")
        evil_tool = make_aggregate_tool(task.items)
        try:
            evil_tool.invoke({"code": EVIL_AGGREGATE_CODE})
        except Exception as exc:  # noqa: BLE001 - 恶意代码必须在这里停下
            print(f"恶意代码被工具拒绝：{type(exc).__name__}: {exc}")
        else:
            raise AssertionError("恶意代码没有被拦住")
        state = run_code_mode(task.items)
        print(f"Agent 实际调用工具：{tool_names(state)}；最终回答：{final_text(state)}")
        aggregated = json.loads(next(message for message in state["messages"] if message.type == "tool").content)
        print("技能 Top5：" + "，".join(f"{skill} {count}" for skill, count in sorted(aggregated.items(), key=lambda pair: -pair[1])[:5]))
        assert "run_aggregate_code" in tool_names(state) and aggregated == dict(expected)
    assert safe_eval("max(1, 3)") == 3 and len(make_resumes(50)) == 50
if __name__ == "__main__":
    main()
