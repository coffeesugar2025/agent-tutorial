"""第 15 章：可观测性与评测 —— 用数据证明 Agent 变好了。

用 LangChain 1.x 的 `create_agent` 跑 20 条 Golden Case，用 `TracerCallbackHandler`
（子类 `CaseTracer`）采集 LLM 调用、工具调用与 token，再算成功率、P50/P95、成本，
输出 bad case 表，对比 baseline / improved，并用 MockJudge 演示 LLM-as-judge 的偏差。

离线运行：python code/ch15_eval.py（不联网、不需要 API Key）
接真实模型：把 `MockChatModel(script=...)` 换成 `get_chat_model()`，删掉脚本函数即可。
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from common.data import DATA_DIR, all_policy_documents, candidates, employee, employees, tickets
from common.lc import MockChatModel, TracerCallbackHandler, final_text

VERSIONS = ("baseline", "improved")
PRICE_IN, PRICE_OUT = 2.0, 8.0  # 元 / 百万 token：示例单价，真实价格以厂商官网为准
MAX_DROP = 0.02  # 回归门禁：成功率下降不得超过 2%
BOUNDARY = ("开除", "解雇", "辞退", "裁员", "天气", "年会")  # 超出服务范围的高风险/无关话题
SYSTEM_PROMPT = "你是 HR 服务台助手。制度类问题必须给出文档编号与条款；无依据或超出范围时转人工。"
# 改进版同义词扩展：让「5 年以上」也能召回「满 5 年」。它也会引入噪声，G02/G03 的失败来自这里。
SYNONYMS = {"年假": {"司龄", "天数", "结转", "折算"}, "病假": {"医院", "证明", "材料"},
            "报销": {"自然日", "发票"}, "远程": {"试用期", "居家"}, "offer": {"审批", "职级"}}
INDEX: list[dict] = []


def build_index() -> list[dict]:
    """一个证据单元 = 一个小节（## 或 ###），带文档编号/版本/状态，方便引用与版本过滤。"""
    units: list[dict] = []
    for doc in all_policy_documents():
        section, lines = "正文", []
        for raw in [*doc["content"].splitlines(), "## __end__"]:
            line = raw.strip()
            if not line.startswith("##"):
                lines.append(line)
                continue
            body = [item for item in lines if item and not item.startswith(("#", ">"))]
            if body:
                units.append({"doc_id": doc["doc_id"], "title": doc["title"], "version": doc["version"],
                              "status": doc["status"], "section": section, "lines": body})
            section, lines = line.lstrip("#").strip(), []
    return units


def tokens(text: str) -> set[str]:
    """中文 bigram + 英文/数字整词：够用、可解释，不依赖向量库。"""
    lowered = text.lower()
    result = set(re.findall(r"[a-z0-9][a-z0-9.\-]*", lowered))
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        result.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return result


def retrieve(question: str, version: str) -> list[dict]:
    """改进版：同义词扩展 + 只查有效版本；baseline：原样查全库，取第一条。"""
    query, pool = tokens(question), INDEX
    if version == "improved":
        for keyword, extra in SYNONYMS.items():
            if keyword in question.lower():
                query |= extra
        pool = [unit for unit in INDEX if unit["status"] == "active"]
    return sorted(pool, key=lambda unit: -sum(
        2.0 if re.fullmatch(r"[a-z0-9.\-]+", token) else 1.0
        for token in query & tokens(f"{unit['section']}\n" + "\n".join(unit["lines"]))))[:1]


def pick_lines(question: str, unit: dict, limit: int) -> str:
    """从命中的小节里挑最贴近问题的几行——这里最容易丢数字，G02 就栽在这。"""
    query = tokens(question)
    scored = sorted(unit["lines"], key=lambda text: -len(query & tokens(text)))
    clean = [re.sub(r"\s+", " ", text.replace("|", " ").replace("**", "")).strip(" -；。")
             for text in scored[:limit] if query & tokens(text)]
    return "；".join(clean) or unit["lines"][0]


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


# ---------- 工具层：@tool 的 docstring 与类型标注就是给模型看的 JSON Schema ----------
@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工当年年假余额。参数是工号，如 E1001。"""
    leave = (employee(employee_id) or {}).get("leave", {})
    total, used = leave.get("annual_total", 0), leave.get("annual_used", 0)
    return _json({"ok": True, "total": total, "used": used, "annual_remaining": total - used})


@tool
def search_policy(query: str, version: str) -> str:
    """检索制度条款。version=baseline 查全库；version=improved 只查有效版本并扩展同义词。"""
    hits = retrieve(query, version)
    return _json({"ok": bool(hits), "hits": hits})


@tool
def search_candidates(query: str) -> str:
    """按技能或岗位关键词检索候选人。"""
    words = set(re.findall(r"[a-zA-Z0-9]+", query))
    words |= {word for word in ("算法", "前端", "后端", "产品", "测试", "数据") if word in query}
    found = [item for item in candidates()
             if any(word.lower() in f"{item['position']} {' '.join(item['skills'])} {item['note']}".lower()
                    for word in words)]
    return _json({"ok": bool(found), "items": found[:3]})


@tool
def get_candidate(name: str) -> str:
    """按姓名查询候选人当前流程阶段。"""
    return _json({"ok": True, "candidate": next((c for c in candidates() if c["name"] == name), None)})


@tool
def get_ticket(ticket_id: str) -> str:
    """按工单号查询工单状态，如 T2026002。"""
    return _json({"ok": True, "ticket": next((t for t in tickets() if t["id"] == ticket_id), None)})


@tool
def check_leave_eligibility(employee_id: str, days: int) -> str:
    """校验年假余额是否够用。days 是本次申请天数。"""
    leave = (employee(employee_id) or {}).get("leave", {})
    remain = leave.get("annual_total", 0) - leave.get("annual_used", 0)
    if remain < days:
        return _json({"ok": False, "reason": f"余额不足（剩 {remain} 天）"})
    return _json({"ok": True, "remaining": remain})


@tool
def submit_leave_request(employee_id: str, days: int, start: str, end: str) -> str:
    """提交年假申请（写操作）：只创建待审批单，不直接生效。"""
    return _json({"ok": True, "days": days, "start": start, "end": end,
                  "request_id": f"LR-{start.replace('-', '')}-001", "status": "待审批"})


@tool
def schedule_interview(name: str, time: str) -> str:
    """创建面试安排（写操作）：需用人经理审批后才发送邀请。"""
    return _json({"ok": True, "name": name, "time": time, "status": "待审批"})


@tool
def adjust_salary(employee_id: str, to_band: str) -> str:
    """创建调薪审批单（高风险写操作，绝不直接改薪资）。"""
    emp = employee(employee_id) or {}
    return _json({"ok": True, "name": emp.get("name", ""), "from_band": emp.get("salary_band", ""),
                  "to_band": to_band, "status": "pending_approval"})


@tool
def start_onboarding(name: str, date: str) -> str:
    """启动新员工入职流程（写操作）。"""
    return _json({"ok": True, "name": name, "date": date, "flow_id": "ONB-2026-1201"})


TOOLS = [get_leave_balance, search_policy, search_candidates, get_candidate, get_ticket,
         check_leave_eligibility, submit_leave_request, schedule_interview, adjust_salary, start_onboarding]


def _find_name(text: str) -> str:
    names = [item["name"] for item in candidates()] + [item["name"] for item in employees()]
    return next((name for name in names if name in text), "")


def _grab(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    return found.group(0) if found else ""


def _days(text: str) -> int:
    found = re.search(r"(\d+)\s*天", text)
    return int(found.group(1)) if found else 1


BASELINE_RULES = (("leave_policy", ("年假", "休假", "假")), ("candidate_search", ("候选人", "简历", "推荐", "招")),
                  ("interview_schedule", ("面试",)), ("salary_adjust", ("薪资", "调薪")),
                  ("onboarding", ("入职",)), ("ticket_query", ("工单", "t2026")))
# v2 的规则：顺序即优先级，先判边界，再按「动词 + 宾语」区分查询与写操作。
IMPROVED_RULES = (("apply_leave", r"(提交|申请).*(假|休假)|休\s*\d+\s*天"),
                  ("candidate_query", r"到哪一步|进展|进度|状态"), ("interview_schedule", r"(安排|约).*面试|面试.*(安排|约)"),
                  ("salary_adjust", r"薪资|调薪|涨薪"), ("onboarding", r"入职"), ("ticket_query", r"T\d{7}|工单"),
                  ("candidate_search", r"候选人|简历|推荐|招"))


def route(text: str, version: str) -> str:
    if version == "baseline":  # v1：只按「像哪一类」硬匹配，没有边界判断，也没有「查进度/提交申请」
        for intent, keywords in BASELINE_RULES:
            if any(word in text.lower() for word in keywords):
                return intent
        return "leave_policy"
    if any(word in text for word in BOUNDARY):
        return "out_of_scope"
    for intent, pattern in IMPROVED_RULES:
        if re.search(pattern, text) and (intent != "candidate_query" or _find_name(text)):
            return intent
    return "leave_balance" if re.search(r"还剩|余额|还有.*几天|我.*几天年假", text) else "leave_policy"


# 意图 → 工具调用计划。真实模型由自己决定，离线脚本用规则模拟这个决策。
def plan(intent: str, case: dict, version: str) -> list[tuple[str, dict]]:
    text, eid = case["input"], case["employee_id"]
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if intent == "leave_balance":
        return [("get_leave_balance", {"employee_id": eid})]
    if intent == "leave_policy":
        return [("search_policy", {"query": text, "version": version})]
    if intent == "apply_leave":
        return [("check_leave_eligibility", {"employee_id": eid, "days": _days(text)}),
                ("submit_leave_request", {"employee_id": eid, "days": _days(text),
                                          "start": dates[0], "end": dates[-1]})]
    if intent == "candidate_search":
        return [("search_candidates", {"query": text})]
    if intent == "candidate_query":
        return [("get_candidate", {"name": _find_name(text)})]
    if intent == "interview_schedule":
        return [("schedule_interview", {"name": _find_name(text),
                                        "time": _grab(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", text)})]
    if intent == "salary_adjust":
        return [("adjust_salary", {"employee_id": (employee(_find_name(text)) or {}).get("id", ""),
                                   "to_band": _grab(r"P\d-\d", text)})]
    if intent == "onboarding":
        return [("start_onboarding", {"name": _find_name(text), "date": dates[0] if dates else ""})]
    if intent == "ticket_query":
        return [("get_ticket", {"ticket_id": _grab(r"T\d{7}", text)})]
    return []


STATUS_CN = {"open": "待处理", "in_progress": "处理中", "resolved": "已解决"}
REFUSAL = "这个问题我无法回答，也不在 HR 服务台的服务范围内，已转人工：HR 同事会在 1 个工作日内联系你。"
# 同一意图两版话术：improved 必须写清依据 / 审批 / 下一步，baseline 只报结果。
REPLIES = {
    "leave_balance": ("你还有 {annual_remaining} 天年假（年度 {total} 天，已用 {used} 天）。", "你还有 {annual_remaining} 天年假。"),
    "interview_schedule": ("已为候选人 {name} 创建面试安排（{time}），待用人经理审批后发送邀请。", "已为 {name} 安排 {time} 的面试。"),
    "onboarding": ("入职流程已启动：{name}，入职日期 {date}，待 HR 校验离职证明与学历材料。", "已开始办理 {name} 的入职，日期 {date}。"),
    "salary_adjust": ("已创建调薪审批单：{name} {from_band} → {to_band}，需 HR 总监与部门 VP 审批，审批通过后生效。",
                      "已记录 {name} 的调薪请求：{from_band} → {to_band}。"),
}


def compose(intent: str, case: dict, results: list[tuple[str, dict]], version: str) -> str:
    strict, text = version == "improved", case["input"]
    data = results[0][1] if results else {}
    if intent == "out_of_scope":
        return REFUSAL
    if intent == "leave_policy":
        if not data.get("hits"):
            return "没有检索到可引用的制度条款，证据不足，已转人工确认。"
        unit = data["hits"][0]
        body = pick_lines(text, unit, 2 if strict else 3)
        if strict:  # 改进版必须带出处：文档编号 + 版本 + 小节
            return f"依据《{unit['title']}》（{unit['doc_id']}，版本 {unit['version']}）第「{unit['section']}」节：{body}。"
        return f"根据制度：{body}。"
    if intent == "apply_leave":
        if not data.get("ok"):
            return f"无法提交：{data['reason']}，建议先确认余额或改期。"
        data = results[1][1]
        return f"已提交 {data['days']} 天年假申请（{data['start']} 至 {data['end']}），单号 {data['request_id']}，当前状态待审批。"
    if intent in REPLIES:
        return (REPLIES[intent][0] if strict else REPLIES[intent][1]).format(**data)
    if intent == "candidate_search":
        items = data["items"]
        if not items:
            return "没有匹配到候选人，建议放宽技能或城市条件。"
        return f"找到 {len(items)} 位候选人：" + "、".join(f"{i['name']}（{i['position']}，匹配技能 {i['skills'][0]}）" for i in items) + "。"
    if intent == "candidate_query":
        item = data["candidate"] or {}
        return f"{item.get('name')} 当前处于 {item.get('stage')} 阶段（{item.get('position')}，期望 {item.get('expected_salary_k')}K，{item.get('available_date')} 可到岗）。"
    item = data["ticket"] or {}
    return f"工单 {item.get('id')} 状态：{STATUS_CN.get(item.get('status'))}，标题《{item.get('title')}》。"


def make_script(case: dict, version: str, meta: dict):
    """离线“模型”：按规则模拟真实模型的决策，保证评测可复现。"""

    def script(messages, tools):
        # create_agent 会把 system_prompt 变成第一条消息，所以取最后一条 HumanMessage
        question = next((str(message.content) for message in reversed(messages)
                         if isinstance(message, HumanMessage)), "")
        intent = meta.setdefault("intent", route(question, version))
        tool_msgs = [message for message in messages if isinstance(message, ToolMessage)]
        if intent == "out_of_scope":
            return {"content": REFUSAL}
        steps = plan(intent, case, version)
        if not tool_msgs:  # 第一轮：决定调哪些工具（写操作先校验，再提交）
            calls = steps[:1] if intent == "apply_leave" else steps
            return {"tool_calls": [{"name": name, "args": args} for name, args in calls]}
        if intent == "apply_leave" and len(tool_msgs) == 1:  # 第二轮：余额够才提交
            check = json.loads(tool_msgs[0].content)
            if not check.get("ok"):
                return {"content": f"无法提交：{check['reason']}，建议先确认余额或改期。"}
            return {"tool_calls": [{"name": steps[1][0], "args": steps[1][1]}]}
        results = [(message.name, json.loads(message.content)) for message in tool_msgs]
        return {"content": compose(intent, case, results, version)}

    return script


class CaseTracer(TracerCallbackHandler):
    """在公共回调的基础上记录一条时间线，等价于一次运行的 Trace。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = time.perf_counter()
        self.timeline: list[dict] = []

    def _mark(self, step: str, **extra) -> None:
        self.timeline.append({"step": step, "ms": round((time.perf_counter() - self.started) * 1000, 2), **extra})

    def on_llm_end(self, response, **kwargs) -> None:
        super().on_llm_end(response, **kwargs)
        self._mark("llm", call=self.llm_calls)

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        super().on_tool_start(serialized, input_str, **kwargs)
        self._mark(f"tool:{serialized.get('name', 'tool')}")

    def print_trace(self, name: str) -> None:
        summary = self.summary()
        print(f"\nTRACE {name}  {self.timeline[-1]['ms'] if self.timeline else 0}ms")
        for item in self.timeline:
            print(f"  - {item['step']} ({item['ms']}ms)")
        print(f"  llm={summary['llm_calls']} tool={summary['tool_calls']} "
              f"token={summary['total_tokens']} error={summary['tool_errors']}")


def run_case(case: dict, version: str) -> dict:
    meta: dict = {}
    model = MockChatModel(script=make_script(case, version, meta))
    agent = create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT)
    tracer = CaseTracer()
    started = time.perf_counter()
    state = agent.invoke({"messages": [HumanMessage(case["input"])]},
                         config={"callbacks": [tracer], "recursion_limit": 10})
    latency = (time.perf_counter() - started) * 1000
    answer = final_text(state)
    summary = tracer.summary()
    intent = meta.get("intent", "unknown")
    checks = {"intent": intent == case["expected_intent"],
              "tools": sorted(summary["tools"]) == sorted(case["expected_tools"]),
              "include": all(re.sub(r"\s+", "", word) in re.sub(r"\s+", "", answer)
                             for word in case["must_include"])}
    checks["success"] = all(checks.values())
    return {"id": case["id"], "input": case["input"], "intent": intent, "expected_intent": case["expected_intent"],
            "tools": summary["tools"], "expected_tools": case["expected_tools"], "answer": answer, "checks": checks,
            "latency_ms": latency, "tokens": summary["total_tokens"],
            "cost": summary["prompt_tokens"] / 1e6 * PRICE_IN + summary["completion_tokens"] / 1e6 * PRICE_OUT,
            "tracer": tracer, "llm_calls": summary["llm_calls"]}


def pct(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))]


def evaluate(cases: list[dict], version: str) -> dict:
    records = [run_case(case, version) for case in cases]
    rate = lambda key: sum(record["checks"][key] for record in records) / len(records)  # noqa: E731
    return {"records": records, "metrics": {
        "version": version, "成功": rate("success"), "意图": rate("intent"), "工具集": rate("tools"), "关键词命中": rate("include"),
        "P50(ms)": pct([r["latency_ms"] for r in records], 0.50), "P95(ms)": pct([r["latency_ms"] for r in records], 0.95),
        "平均token": statistics.mean([r["tokens"] for r in records]),
        "平均LLM调用": statistics.mean([r["llm_calls"] for r in records]),
        "总成本(元)": sum(r["cost"] for r in records)}}


def judge(record: dict) -> dict:
    """假评委：有引用 +1、篇幅够长 +1、正确拒答 -1——偏差就藏在这三条规则里。"""
    answer, score = record["answer"], 3
    score += 1 if "《" in answer else 0
    score += 1 if len(answer) >= 25 else 0
    score -= 1 if ("无法" in answer or "转人工" in answer) else 0  # 偏差 1：正确拒答被判低分
    score = max(1, min(5, score))
    return {"id": record["id"], "score": score, "success": record["checks"]["success"], "judged_pass": score >= 4}


def main() -> None:
    global INDEX
    lines = (DATA_DIR / "golden_cases.jsonl").read_text(encoding="utf-8").splitlines()
    cases, INDEX = [json.loads(line) for line in lines if line.strip()], build_index()
    print(f"=== 1. 三支柱：Trace / Log / Metric（{len(cases)} 条用例，{len(INDEX)} 个证据单元）===")
    reports = {version: evaluate(cases, version) for version in VERSIONS}
    sample = next(r for r in reports["improved"]["records"] if not r["checks"]["success"])
    sample["tracer"].print_trace(f"improved-{sample['id']}")
    print("\n[log] " + json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                                   "case_id": sample["id"], "intent": sample["intent"],
                                   "tools": sample["tools"], "latency_ms": round(sample["latency_ms"], 3),
                                   "tokens": sample["tokens"], "success": sample["checks"]["success"]},
                                  ensure_ascii=False))

    print("\n=== 2. 逐条结果与 Bad Case（B=baseline I=improved）===")
    for base, imp in zip(reports["baseline"]["records"], reports["improved"]["records"]):
        failed = ",".join(key for key in ("intent", "tools", "include") if not imp["checks"][key]) or "-"
        print(f"{base['id']} {base['input'][:12]:<14}B={'Y' if base['checks']['success'] else 'N'}"
              f" I={'Y' if imp['checks']['success'] else 'N'}  I失败项={failed}")

    print("\n=== 3. 核心指标对比 ===")
    for key in ("成功", "意图", "工具集", "关键词命中", "P50(ms)", "P95(ms)", "平均token", "平均LLM调用", "总成本(元)"):
        base, imp = (reports[version]["metrics"][key] for version in VERSIONS)
        pattern = "{:.2%}" if key in ("成功", "意图", "工具集", "关键词命中") else ("{:.3f}" if isinstance(base, float) else "{}")
        print(f"{key:<10}{pattern.format(base):<12}{pattern.format(imp)}")
    print(f"单任务成本约 {reports['improved']['metrics']['总成本(元)'] / len(cases):.6f} 元（示例单价 {PRICE_IN}/{PRICE_OUT} 元每百万 token）")

    print("\n=== 4. MockJudge：LLM-as-judge 与它的偏差 ===")
    for version in VERSIONS:
        verdicts = [judge(record) for record in reports[version]["records"]]
        agree = sum(v["judged_pass"] == v["success"] for v in verdicts)
        print(f"{version:<10} 平均分 {statistics.mean(v['score'] for v in verdicts):.2f}/5，与人工判定一致 {agree}/{len(verdicts)}")
    disagree = [v for v in (judge(r) for r in reports["improved"]["records"]) if v["judged_pass"] != v["success"]]
    for verdict in disagree[:4]:
        record = next(r for r in reports["improved"]["records"] if r["id"] == verdict["id"])
        print(f"  分歧 {record['id']}：评委 {verdict['score']} 分，人工判定"
              f"{'成功' if record['checks']['success'] else '失败'}｜{record['answer'][:26]}…")
    print("偏差：排版好、有引用的答案更容易得高分；正确拒答反而被扣分。评委分不能替代人工标注。")

    print("\n=== 5. 回归门禁 ===")
    drop = reports["baseline"]["metrics"]["成功"] - reports["improved"]["metrics"]["成功"]
    ok = drop <= MAX_DROP
    print(("PASS " if ok else "FAIL ") + f"成功率 {reports['baseline']['metrics']['成功']:.0%} → "
          f"{reports['improved']['metrics']['成功']:.0%}（变化 {-drop:+.0%}；门禁：下降不得超过 {MAX_DROP:.0%}）")
    assert len(reports["improved"]["records"]) == 20, "Golden Case 必须跑满 20 条"
    assert reports["improved"]["metrics"]["成功"] > reports["baseline"]["metrics"]["成功"], "改进版必须优于 baseline"
    assert reports["improved"]["metrics"]["成功"] >= 0.90, "改进版成功率需达到 90% 以上"
    assert ok and disagree, "门禁必须通过，且评委必须出现与人工判定不一致的样本"
    print("=== 6. 断言全部通过：改进有效、门禁可执行、评委确实有偏差。===")
    print("练习：清空 SYNONYMS 再跑，看 G03 翻绿而 G02 仍失败；再让 pick_lines 优先含数字的行，看能否到 100%。")


if __name__ == "__main__":
    main()
