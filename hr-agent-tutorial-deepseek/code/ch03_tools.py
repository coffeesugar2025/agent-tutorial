"""第 03 章：Tool Calling —— 用 LangChain 工具把 HR 系统变成模型的手脚。

运行：python code/ch03_tools.py
离线演示：MockChatModel 按脚本发起工具调用；真实模型只需换 get_chat_model。
"""

from __future__ import annotations

import contextvars
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from common.data import candidate, candidates, employees
from common.lc import MockChatModel, TracerCallbackHandler, final_text, tool_names

READ_ROLES = ("recruiter", "hrbp", "auditor")
SYSTEM_PROMPT = "你是招聘助手。只调用已注册工具；先查证，再执行写操作。"

@dataclass
class ToolResult:
    """自定义工具包装层的统一返回：模型只看到 ok/data/error/code。"""

    ok: bool
    data: Any = None
    error: str | None = None
    code: str = ""
    retryable: bool = False

    def to_message(self) -> dict:
        if self.ok:
            return {"ok": True, "data": self.data}
        return {"ok": False, "error": self.error, "code": self.code, "retryable": self.retryable}

@dataclass
class ToolContext:
    actor: str
    role: str

CURRENT_CTX: contextvars.ContextVar[ToolContext] = contextvars.ContextVar(
    "hr_tool_ctx", default=ToolContext("anonymous", "intern")
)

def fail(code: str, message: str, retryable: bool = False) -> ToolResult:
    return ToolResult(ok=False, error=message, code=code, retryable=retryable)

def run_tool(name: str, params: BaseModel, handler: Callable, roles: tuple[str, ...]) -> dict:
    """权限、异常、统一返回都留在包装层；LangChain 只负责调度与回填。"""
    ctx = CURRENT_CTX.get()  # 请求级上下文，真实系统可用 ToolRuntime/租户上下文注入
    if ctx.role not in roles:
        return fail("FORBIDDEN", f"角色 {ctx.role} 无权调用 {name}，需要 {roles}").to_message()
    try:
        return handler(params, ctx).to_message()
    except Exception as exc:  # noqa: BLE001 - 工具异常必须变成结构化结果
        return fail("TOOL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True).to_message()

class SearchCandidatesParams(BaseModel):
    query: str = Field(min_length=1, max_length=20, description="岗位、姓名或技能关键词，如 后端、RAG")
    city: str | None = Field(default=None, description="城市，如 上海；不传表示不限")
    min_years: int = Field(default=0, ge=0, le=40, description="最低工作年限")

class InterviewerSlotsParams(BaseModel):
    interviewer_id: str = Field(pattern=r"^E\d{4}$", description="面试官员工号，如 E2001")
    date: str = Field(default="2026-11-18", pattern=r"^\d{4}-\d{2}-\d{2}$", description="面试日期")

class ScheduleInterviewParams(BaseModel):
    candidate_id: str = Field(pattern=r"^C\d{3}$", description="候选人编号，如 C001")
    interviewer_id: str = Field(pattern=r"^E\d{4}$", description="面试官员工号，如 E2001")
    slot: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", description="面试时间，如 2026-11-18 14:00")
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64, description="幂等键；留空则用业务自然键")

def _search_candidates(params: SearchCandidatesParams, ctx: ToolContext) -> ToolResult:
    time.sleep(0.05)  # 模拟数据库往返，用来观察同一轮工具调用的并发
    rows = []
    for item in candidates():
        text = " ".join([item["position"], item["name"], *item["skills"]]).lower()
        if params.query.lower() not in text:
            continue
        if (params.city and item["city"] != params.city) or item["years"] < params.min_years:
            continue
        rows.append({k: item[k] for k in ("id", "name", "position", "city", "years", "skills", "stage", "score")})
    rows.sort(key=lambda row: (-row["score"], row["id"]))
    return ToolResult(True, {"count": len(rows), "items": rows, "masked": True})

def _slots_for(interviewer_id: str, date: str) -> list[str]:
    hours = ("14:00", "16:00") if int(interviewer_id[-1]) % 2 else ("10:00", "14:00", "16:00")
    return [f"{date} {hour}" for hour in hours]

def _get_slots(params: InterviewerSlotsParams, ctx: ToolContext) -> ToolResult:
    time.sleep(0.05)
    person = next((item for item in employees() if item["id"] == params.interviewer_id), None)
    if person is None:
        return fail("NOT_FOUND", f"员工 {params.interviewer_id} 不存在")
    booked = {row["slot"] for row in _SCHEDULES if row["interviewer_id"] == params.interviewer_id}
    slots = [slot for slot in _slots_for(params.interviewer_id, params.date) if slot not in booked]
    return ToolResult(True, {"interviewer": person["name"], "date": params.date, "slots": slots})

_IDEMPOTENCY: dict[str, dict] = {}
_SCHEDULES: list[dict] = []
_LOCK = threading.Lock()

def _schedule(params: ScheduleInterviewParams, ctx: ToolContext) -> ToolResult:
    person = candidate(params.candidate_id)
    interviewer = next((item for item in employees() if item["id"] == params.interviewer_id), None)
    if person is None or interviewer is None:
        return fail("NOT_FOUND", "候选人或面试官不存在")
    key = params.idempotency_key or f"natural:{params.candidate_id}:{params.interviewer_id}:{params.slot}"
    with _LOCK:  # 幂等表与日程表必须一起检查、一起写入
        if key in _IDEMPOTENCY:
            return ToolResult(True, {**_IDEMPOTENCY[key], "replayed": True})
        if params.slot not in _slots_for(params.interviewer_id, params.slot[:10]):
            return fail("SLOT_UNAVAILABLE", f"{params.slot} 不是 {interviewer['name']} 的空闲时段")
        if any(row["interviewer_id"] == params.interviewer_id and row["slot"] == params.slot for row in _SCHEDULES):
            return fail("SLOT_TAKEN", "该时段已被占用，请换一个 slot")
        record = {"interview_id": f"IV{len(_SCHEDULES) + 1:04d}",
                  "candidate": f"{person['id']} {person['name']}",
                  "interviewer": f"{interviewer['id']} {interviewer['name']}",
                  "slot": params.slot, "status": "confirmed", "invites_sent": 2}
        _SCHEDULES.append(record)
        _IDEMPOTENCY[key] = record
        return ToolResult(True, dict(record))

@tool("search_candidates", args_schema=SearchCandidatesParams)
def search_candidates(query: str, city: str | None = None, min_years: int = 0) -> dict:
    """按关键词、城市、最低年限搜索候选人。只读；返回脱敏列表，不含手机号与邮箱。"""
    return run_tool("search_candidates", SearchCandidatesParams(query=query, city=city, min_years=min_years),
                    _search_candidates, READ_ROLES)

@tool("get_interviewer_slots", args_schema=InterviewerSlotsParams)
def get_interviewer_slots(interviewer_id: str, date: str = "2026-11-18") -> dict:
    """查询面试官在指定日期的空闲时段。只读；返回 slots 列表。"""
    return run_tool("get_interviewer_slots", InterviewerSlotsParams(interviewer_id=interviewer_id, date=date),
                    _get_slots, READ_ROLES)

@tool("schedule_interview", args_schema=ScheduleInterviewParams)
def schedule_interview(candidate_id: str, interviewer_id: str, slot: str, idempotency_key: str | None = None) -> dict:
    """创建面试日程并发送邀请。写操作；同一幂等键重复调用只发一次。"""
    params = ScheduleInterviewParams(candidate_id=candidate_id, interviewer_id=interviewer_id,
                                     slot=slot, idempotency_key=idempotency_key)
    return run_tool("schedule_interview", params, _schedule, ("recruiter",))

TOOLS = [search_candidates, get_interviewer_slots, schedule_interview]

def run(script: list[dict], role: str, prompt: str) -> tuple[dict, TracerCallbackHandler, float]:
    CURRENT_CTX.set(ToolContext("E1010 郑爽", role))
    agent = create_agent(model=MockChatModel(script=script), tools=TOOLS, system_prompt=SYSTEM_PROMPT)
    tracer = TracerCallbackHandler()
    started = time.perf_counter()
    state = agent.invoke({"messages": [{"role": "user", "content": prompt}]},
                         config={"callbacks": [tracer], "recursion_limit": 12})
    return state, tracer, round(time.perf_counter() - started, 3)

def main() -> None:
    print("=== 1. LangChain 工具：args_schema 自动生成给模型看的 Schema ===")
    for item in TOOLS:
        print(f"- {item.name}: {item.description[:38]}")
        print(f"  args={item.args}")

    print("\n=== 2. create_agent 并行执行同一轮的两个只读工具 ===")
    parallel_script = [
        {"content": "我先同时查候选人和面试官空闲时间。", "tool_calls": [
            {"name": "search_candidates", "args": {"query": "后端", "city": "上海", "min_years": 3}},
            {"name": "get_interviewer_slots", "args": {"interviewer_id": "E2001"}},
        ]},
        {"content": "查到了，可以约面试。"},
    ]
    state, tracer, elapsed = run(parallel_script, "recruiter", "帮林晓约徐明面试")
    print(f"最终回答：{final_text(state)}")
    print(f"工具序列：{tool_names(state)}；耗时 {elapsed}s（串行约 0.10s）")
    print(f"回调统计：{tracer.summary()}")

    print("\n=== 3. 参数错误：args_schema 在工具执行前拦住 ===")
    try:
        search_candidates.invoke({"query": "后端", "min_years": "五年"})
    except ValidationError as exc:
        bad = exc.errors()[0]
        print(f"ValidationError -> {bad['loc']}: {bad['msg']}")
    else:
        bad = {"type": "none"}

    print("\n=== 4. 权限拒绝：实习生可以查，不能约 ===")
    denied_state, _, _ = run(
        [{"tool_calls": [{"name": "schedule_interview",
                          "args": {"candidate_id": "C001", "interviewer_id": "E2001", "slot": "2026-11-18 14:00"}}]},
         {"content": "我没有写权限，请让招聘专员处理。"}],
        "intern", "帮我约林晓面试",
    )
    denied = [m for m in denied_state["messages"] if isinstance(m, ToolMessage)][-1]
    print(f"工具返回：{denied.content}")

    print("\n=== 5. 幂等：同一键重试，只发一次邀请 ===")
    arguments = {"candidate_id": "C001", "interviewer_id": "E2001", "slot": "2026-11-18 14:00",
                 "idempotency_key": "interview:C001:E2001:round1"}
    first_state, _, _ = run([{"tool_calls": [{"name": "schedule_interview", "args": arguments}]},
                             {"content": "已安排。"}], "recruiter", "约林晓面试")
    second_state, _, _ = run([{"tool_calls": [{"name": "schedule_interview", "args": arguments}]},
                              {"content": "已安排。"}], "recruiter", "重试约林晓面试")
    first = json.loads([m for m in first_state["messages"] if isinstance(m, ToolMessage)][-1].content)
    second = json.loads([m for m in second_state["messages"] if isinstance(m, ToolMessage)][-1].content)
    print(f"第一次：{first['data']['interview_id']}；第二次 replayed={second['data']['replayed']}")
    print(f"实际日程 {len(_SCHEDULES)} 条，邀请 {sum(item['invites_sent'] for item in _SCHEDULES)} 封")

    print("\n=== 6. 断言 ===")
    assert tool_names(state) == ["search_candidates", "get_interviewer_slots"]
    assert bad["type"] == "int_parsing"
    assert "FORBIDDEN" in denied.content
    assert first["data"]["interview_id"] == second["data"]["interview_id"] and second["data"]["replayed"]
    assert len(_SCHEDULES) == 1
    print("全部通过：LangChain 工具、并行只读、参数校验、权限与幂等都符合预期。")

if __name__ == "__main__":
    main()
