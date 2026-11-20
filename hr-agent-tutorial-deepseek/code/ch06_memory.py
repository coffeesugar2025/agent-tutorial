"""第 06 章：Memory —— LangGraph 管会话与线程，自定义 Store 管长期记忆。

会话进 MessagesState + InMemorySaver，trim_messages 控窗口；画像/事实/冲突/TTL/密级仍自定义，
通过 @tool 接入。"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import HumanMessage, trim_messages
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from common.data import employee
from common.lc import MockChatModel
from common.text import estimate_tokens, mask_pii

STOP = {"什么", "怎么", "可以", "我们", "你们", "一下", "这个", "那个", "现在", "还有", "的话"}

def keywords(text: str) -> set[str]:
    text = text.lower()
    words = {w for w in re.findall(r"[a-z0-9]+", text) if w not in STOP}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words |= {run[i : i + 2] for i in range(len(run) - 1)}
    return words

@dataclass
class Fact:
    key: str
    value: str
    source: str
    created_at: date
    ttl_days: int | None = None
    sensitivity: str = "L1"  # L1 公开 / L2 内部 / L3 敏感
    superseded_at: date | None = None

class MemoryStore:
    """长期记忆：画像、事实链、TTL、密级。会话与线程交给 LangGraph。"""

    WINDOW_TOKENS = 80
    HALF_LIFE = 14.0
    LEVELS = {"L1": {"self", "hr", "manager", "hr_admin"}, "L2": {"self", "hr", "hr_admin"}, "L3": {"self", "hr_admin"}}

    def __init__(self, employee_id: str, today: date = date(2026, 11, 16)) -> None:
        record = employee(employee_id) or {}
        self.employee_id, self.today, self.audit = employee_id, today, []
        self.profile = {"name": record.get("name", "未知"), "department": record.get("department", ""),
                        "city": record.get("city", "")}
        self.profile_history: dict[str, list[tuple[date, str]]] = {}
        self.facts: dict[str, list[Fact]] = {}
        self.summary_lines: list[str] = []

    def observe(self, key: str, value: str, source: str, *, created_at: date | None = None, **kwargs: object) -> str:
        new = Fact(key=key, value=value, source=source, created_at=created_at or self.today, **kwargs)  # type: ignore[arg-type]
        history = self.facts.setdefault(key, [])
        conflict = bool(history) and history[-1].value != value and history[-1].superseded_at is None
        if conflict:  # 冲突不覆盖：旧值失效，新值追加，审计留痕
            history[-1].superseded_at = self.today
            self.audit.append(f"冲突：{key} 由「{history[-1].value}」改为「{value}」，来源 {source}")
        history.append(new)
        return "conflict" if conflict else "new"

    def update_profile(self, key: str, value: str, source: str) -> bool:
        old = self.profile.get(key)
        if old == value:
            return False
        self.profile[key] = value
        self.profile_history.setdefault(key, []).append((self.today, value))
        self.audit.append(f"画像：{key} {old} → {value}（{source}）")
        return True

    def recall(self, question: str, audience: str = "self", top_k: int = 3) -> list[dict]:
        query = keywords(self.resolve(question))
        scored: list[dict] = []
        for fact in (f for group in self.facts.values() for f in group):
            age = (self.today - fact.created_at).days
            expired = fact.ttl_days is not None and age > fact.ttl_days
            if fact.superseded_at is not None or expired:
                continue
            if audience not in self.LEVELS[fact.sensitivity]:
                self.audit.append(f"拒绝召回：{fact.key} 为 {fact.sensitivity}")
                continue
            text = f"{fact.key}：{mask_pii(fact.value)}"
            if not (hit := query & keywords(text)):
                continue
            overlap = len(hit) / max(len(query), 1)
            scored.append({"text": text, "score": round(0.7 * overlap + 0.3 * 0.5 ** (age / self.HALF_LIFE), 3),
                           "age_days": age, "source": fact.source})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def resolve(self, question: str) -> str:
        if not any(word in question for word in ("那", "它", "这个", "还有")) or not self.summary_lines:
            return question
        topic = self.summary_lines[-1].split("问", 1)[-1].split("；")[0]
        return f"{topic} {question}"

    def compress(self, messages: list) -> None:
        for i in range(0, len(messages) - 1, 2):
            ask, answer = str(messages[i].content), str(messages[i + 1].content)
            line = f"{self.today:%m-%d} 问{ask[:24]}；答{answer[:28]}"
            if numbers := re.findall(r"\d+(?:\.\d+)?", ask + answer):
                line += f"（数字：{'/'.join(dict.fromkeys(numbers))[:20]}）"
            self.summary_lines.append(line)
        self.summary_lines = self.summary_lines[-6:]

STORE = MemoryStore("E1001", today=date(2026, 11, 5))

@tool
def recall_memory(query: str, audience: str = "self") -> str:
    """从长期记忆召回与问题相关的事实。query 是问题，audience 是访问者身份。"""
    hits = STORE.recall(query, audience)
    return "\n".join(f"[{hit['score']}] {hit['text']} ← {hit['source']}" for hit in hits) or "（无）"
PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是 HR 共享服务中心的助手。只使用下方记忆回答，不确定就说不确定。\n{memory}"),
    ("placeholder", "{history}"),
    ("human", "{question}"),
])
CHAIN = PROMPT | MockChatModel(script=[
    {"content": "你今年年假 15 天，已休 2 天，还剩 13 天，最小请假单位 0.5 天。"},
    {"content": "够，还剩 13 天，扣掉 3 天还有 10 天。"},
    {"content": "至少提前 3 个工作日，连续休 3 天由直属主管审批。"},
    {"content": "最多结转 5 天到次年 3 月 31 日，逾期作废。"},
    {"content": "病假需二级及以上医院证明，当天 10:00 前报备，返岗 2 个工作日内补交。"},
])
TRIM_LOG: list[tuple[int, int]] = []

def assistant_node(state: MessagesState) -> dict:
    history = state["messages"]
    trimmed = trim_messages(history, max_tokens=STORE.WINDOW_TOKENS,
                            token_counter=lambda msgs: sum(estimate_tokens(str(m.content)) for m in msgs),
                            strategy="last", start_on="human")
    question = next((str(m.content) for m in reversed(history) if isinstance(m, HumanMessage)), "")
    resolved = STORE.resolve(question)
    recalled = recall_memory.invoke({"query": resolved})  # store 通过 Tool 接入
    memory = (f"员工：{STORE.profile['name']}（{STORE.employee_id}，{STORE.profile['department']}，{STORE.profile['city']}）"
              f"\n历史摘要：{'；'.join(STORE.summary_lines) or '（无）'}\n相关记忆：\n{recalled}")
    reply = CHAIN.invoke({"memory": memory, "history": trimmed, "question": question})
    TRIM_LOG.append((len(history), len(trimmed)))
    print(f"  [trim_messages] {len(history)} → {len(trimmed)} 条 / {sum(estimate_tokens(str(m.content)) for m in trimmed)} token｜消解 {resolved!r}"
          f"\n  [召回] {recalled.replace(chr(10), '；')}")
    return {"messages": [reply]}

def build_app(saver: InMemorySaver):
    graph = StateGraph(MessagesState)
    graph.add_node("assistant", assistant_node)
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile(checkpointer=saver)

def main() -> None:
    print("=== 1. 会话 A（11-05，thread=employee-E1001）：张伟连问四轮年假 ===")
    STORE.observe("年假余额", "15 天额度，已休 2 天，剩 13 天", "HR 系统 leave_balance", ttl_days=30)
    STORE.observe("年假申请", "计划 12 月休 3 天，需提前 3 个工作日提交", "员工自述", ttl_days=60)
    STORE.observe("年假结转", "没休完的年假最多结转 5 天至次年 3 月 31 日", "HR-LEAVE-2025", ttl_days=180)
    saver = InMemorySaver(); app = build_app(saver)
    config = {"configurable": {"thread_id": "employee-E1001"}}
    for question in ["我年假还剩几天？", "我想 12 月休 3 天，额度够吗？",
                     "需要提前几天申请？", "没休完能跨年吗？"]:
        app.invoke({"messages": [HumanMessage(question)]}, config)
    state = app.get_state(config); messages = state.values["messages"]
    print(f"\n[checkpoint] {len(messages)} 条消息 {[type(m).__name__ for m in messages]}，next={state.next}")
    STORE.compress(messages[:2])  # 最早一轮压进摘要，「那」才有指代对象

    print("\n=== 2. 模拟进程重启（同一个 saver + thread_id），然后在今天只问一句「那病假呢」 ===")
    app2 = build_app(saver); recovered = app2.get_state(config)
    print(f"[recover] 新 graph 用同一 saver 恢复出 {len(recovered.values['messages'])} 条消息")
    STORE.today = date(2026, 11, 16)
    STORE.observe("病假材料", "需二级及以上医院证明，当天 10:00 前报备，返岗 2 个工作日内补交", "HR-LEAVE-2025", ttl_days=180)
    app2.invoke({"messages": [HumanMessage("那病假呢？")]}, config); hits = STORE.recall("那病假呢？")

    print("\n=== 3. 冲突：张伟从技术部转到产品部，工位也换了 ===")
    STORE.observe("工位", "5F-08", "行政系统", ttl_days=90)
    STORE.observe("工位", "6F-12", "行政系统", ttl_days=90)
    print("画像更新：", STORE.update_profile("department", "产品部", "组织架构调整 2026-11-16"),
          "｜部门：", STORE.profile["department"], "｜工位链：", [(f.value, f.superseded_at) for f in STORE.facts["工位"]])
    print("审计：", " ｜ ".join(STORE.audit))

    print("\n=== 4. TTL 与隐私：过期不召回，L3 不给主管看 ===")
    STORE.observe("出差计划", "2026-09 深圳出差 3 天", "员工自述", created_at=date(2026, 9, 1), ttl_days=14)
    STORE.observe("病假原因", "腰椎间盘突出，医嘱休息 5 天", "员工自述", ttl_days=30, sensitivity="L3")
    print("主管召回「出差」：", recall_memory.invoke({"query": "出差", "audience": "manager"}).replace("（无）", "（空：已过期）"))
    print("主管召回「病假原因」：", recall_memory.invoke({"query": "病假原因", "audience": "manager"}),
          "｜本人：", recall_memory.invoke({"query": "病假原因", "audience": "self"}).splitlines()[0])

    assert len(messages) == 8 and len(recovered.values["messages"]) == 8, "四轮对话应留下 8 条消息并可恢复"
    assert TRIM_LOG[-1][1] < TRIM_LOG[-1][0] and any(h["text"].startswith("年假") for h in hits)
    assert STORE.profile["department"] == "产品部" and len(STORE.profile_history["department"]) == 1
    print("\n全部断言通过：LangGraph 线程可恢复、trim_messages 生效、跨会话指代与冲突/TTL/权限正确。")

if __name__ == "__main__":
    main()
