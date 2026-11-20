"""第 17 章：可观测性与评测 —— Trace、Metrics、Golden Case。

跑法：python ch17_observability/main.py

LangChain 的观测入口是 **callback**：
  · BaseCallbackHandler 的 on_llm_start / on_llm_end / on_tool_start / on_tool_end
  · 挂上去之后，你就能拿到每一次模型调用、每一次工具调用的耗时、token、输入输出

然后回答三个业务问题：
  · 成功率多少？（Golden Case 回归）
  · 工具调用准不准？（该调没调 / 调错工具 / 参数错）
  · 幻觉率多少？（答案有没有引用、引用对不对得上）
"""

import sys, pathlib, time, json

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import tool

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 1) Trace：一个 callback 就是最简版的"链路追踪"
# ============================================================
class Tracer(BaseCallbackHandler):
    def __init__(self):
        self.spans: list[dict] = []
        self._t0: dict[str, float] = {}
        self.tool_calls = 0

    def on_llm_start(self, serialized, prompts, **kw):
        self._t0["llm"] = time.perf_counter()

    def on_llm_end(self, response, **kw):
        usage = getattr(response, "llm_output", {}) or {}
        self.spans.append({
            "kind": "llm",
            "ms": round((time.perf_counter() - self._t0.get("llm", time.perf_counter())) * 1000, 1),
            "tokens": usage.get("token_usage", {}).get("total_tokens", 0),
        })

    def on_tool_start(self, serialized, input_str, **kw):
        self._t0["tool"] = time.perf_counter()
        self.tool_calls += 1

    def on_tool_end(self, output, **kw):
        self.spans.append({"kind": "tool",
                           "ms": round((time.perf_counter() - self._t0.get("tool", time.perf_counter())) * 1000, 1)})


@tool("get_leave_balance")
def get_leave_balance(emp_id: str) -> str:
    """查员工 2026 年年假余额。"""
    return f"{emp_id} 2026 年年假剩 7 天"


@tool("get_headcount")
def get_headcount(dept: str) -> str:
    """按部门查在职人数。"""
    return f"{dept} 在职 3 人"


title("案例 1：给 Agent 挂 Tracer，看清每一步花了多久")

tracer = Tracer()
model = get_model([ai_tool("get_leave_balance", {"emp_id": "E1001"}, "c1"),
                   ai_text("张伟 2026 年年假剩 7 天。")])
agent = create_agent(model, tools=[get_leave_balance, get_headcount],
                     system_prompt="查数据必须调工具。")
out = agent.invoke({"messages": [{"role": "user", "content": "张伟还有几天年假？"}]},
                   config={"callbacks": [tracer]})
print(f"  回答：{out['messages'][-1].content}")
print(f"  工具调用次数：{tracer.tool_calls}")
for s in tracer.spans:
    print(f"    {s}")
star("Trace 最小可用版就是'每一步的记录'：kind + 耗时 + token。生产上再接到 LangSmith/OTel")

# ============================================================
# 2) Golden Case：把'验收标准'变成可跑的用例
# ============================================================
section("案例 2：Golden Case 回归 —— 改完 prompt 到底变好还是变差")

GOLDEN = [
    {"q": "张伟还有几天年假？", "tool": ("get_leave_balance", {"emp_id": "E1001"}),
     "good": "张伟 2026 年年假剩 7 天。", "bad": "大概还有 5 天吧。", "must_contain": ["7"], "cite": False},
    {"q": "技术中心多少人？", "tool": ("get_headcount", {"dept": "技术中心"}),
     "good": "技术中心在职 3 人。", "bad": "技术中心人挺多的。", "must_contain": ["3"], "cite": False},
    {"q": "年假没休完能折钱吗？", "tool": None,
     "good": "年假未休完不折现，可结转至次年 3 月 31 日。[来源: 年假结转规则]",
     "bad": "应该可以折钱，具体问 HR。", "must_contain": ["不折现", "结转"], "cite": True},
]


def build_script(case, version: str) -> list:
    """★ 用例自己声明'这一版应该怎么答'，这样回归测试可复现、不依赖真实模型。"""
    if version == "v1（合格）":
        return ([ai_tool(case["tool"][0], case["tool"][1], "call")] if case["tool"] else []) + [ai_text(case["good"])]
    return ([ai_tool(case["tool"][0], case["tool"][1], "call")] if case["tool"] else []) + [ai_text(case["bad"])]


def run_case(case, version: str) -> dict:
    model = get_model(build_script(case, version))
    agent = create_agent(model, tools=[get_leave_balance, get_headcount], system_prompt="查数据必须调工具。")
    tr = Tracer()
    res = agent.invoke({"messages": [{"role": "user", "content": case["q"]}]}, config={"callbacks": [tr]})
    ans = res["messages"][-1].content
    used = [m.name for m in res["messages"] if type(m).__name__ == "ToolMessage"]
    ok_tool = (case["tool"] is None) or (case["tool"][0] in used)
    ok_text = all(w in ans for w in case["must_contain"])
    ok_cite = (not case["cite"]) or ("[来源:" in ans)
    return {"q": case["q"], "tool_ok": ok_tool, "text_ok": ok_text, "cite_ok": ok_cite,
            "used": used, "ans": ans[:34]}


for version in ("v1（合格）", "v2（退步）"):
    print(f"\n  {version}：")
    passed = 0
    for case in GOLDEN:
        r = run_case(case, version)
        ok = r["tool_ok"] and r["text_ok"] and r["cite_ok"]
        passed += ok
        flag = "✅" if ok else "❌"
        detail = "" if ok else f"（工具 {r['tool_ok']} 内容 {r['text_ok']} 引用 {r['cite_ok']}）"
        print(f"    {flag} {r['q']}  →  {r['ans']} {detail}")
    print(f"    通过率：{passed}/{len(GOLDEN)} = {passed / len(GOLDEN):.0%}")
    if version == "v2（退步）":
        star("v2 通过率下降 → 这次改动不能合。没有 Golden Case 的'优化'，全是自我感觉良好")

# ============================================================
# 3) 四个指标怎么算
# ============================================================
section("案例 3：上线要看哪四个数")
metrics = [
    ("任务成功率", "Golden Case 通过数 / 总数", "口径要写死：什么算通过"),
    ("工具调用准确率", "该调的调了 + 参数对 / 应调总数", "区分'没调'与'调错参数'"),
    ("幻觉率", "无引用 / 引用对不上原文 的答案占比", "最便宜的度量：引用校验失败率"),
    ("成本与延迟", "每任务 tokens、P50/P95 延迟", "P95 才是用户体验"),
]
for a, b, c in metrics:
    print(f"    {a:<10} = {b:<28} ← {c}")

print("\n  一份可以直接放进周报的指标表：")
report = {"date": "2026-11-15", "success_rate": 0.67, "tool_accuracy": 0.83,
          "hallucination_rate": 0.0, "cost_per_task": 1240, "p95_latency_ms": 3800, "bad_cases": 1}
print("    " + json.dumps(report, ensure_ascii=False))

practice([
    "给 Tracer 加 on_chain_start/end，统计每个节点的耗时占比（找瓶颈）",
    "把 GOLDEN 扩到 10 条，包含 2 条'必须拒答'的用例（资料里没有）",
    "把 tracer.spans 落到 jsonl，写个脚本算 P95",
])
