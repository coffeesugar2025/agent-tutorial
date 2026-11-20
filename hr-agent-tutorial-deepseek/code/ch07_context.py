"""第 07 章：Context Engineering —— LangChain 版上下文预算与 map-reduce 压缩。

trim_messages 做配额，ChatPromptTemplate + RunnableLambda 组装；map 用 Prompt | Model，reduce 用 RunnableLambda。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import BaseMessage, HumanMessage, trim_messages
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_text_splitters import RecursiveCharacterTextSplitter

from common.data import all_policy_documents, load_text
from common.lc import MockChatModel
from common.text import estimate_tokens

PROBES = [("RAG", "你们的 RAG 链路具体怎么搭的？"), ("切片", "切片策略怎么定的，为什么是 400 到 600 字？"),
          ("评估", "召回效果你们怎么评估？"), ("背景", "先介绍下你的背景，重点讲最近两年。")]
OPENERS = ["我先给结论。", "这块我踩过坑，说具体点。", "分两层讲。"]
TAILS = ["当时我们把评估口径先固定下来，每次改动都跑同一套数据，避免拍脑袋。",
         "这件事我负责方案设计和验收标准，上线前跑了三轮对照实验。",
         "我们的原则是宁可多问一句，也不让用户拿到没出处的答案。"]

def build_transcript(target_chars: int = 6000) -> str:
    note = load_text("interview-notes/C003-wanghao.md")
    facts = [line[2:].strip() for line in note.splitlines() if line.startswith("- ")]
    rounds = [f"# 面试逐字稿：王浩 · 算法工程师（C003）\n时间：2026-11-16 ｜ 时长：40 分钟"]
    total, index = 0, 0
    while total < target_chars and index < 60:
        fact = facts[index % len(facts)]
        probe = next((q for key, q in PROBES if key in fact), "再展开讲讲你负责的部分。")
        block = f"面试官：{probe}\n候选人：{OPENERS[index % 3]}{fact}。{TAILS[index % 3]}"
        rounds.append(block)
        total += len(block)
        index += 1
    return "\n\n".join(rounds)

def policy_excerpt(doc_id: str, start: str, chars: int = 300) -> str:
    doc = next(item for item in all_policy_documents() if item["doc_id"] == doc_id)
    body = doc["content"]
    return f"《{doc['title']}》v{doc['version']}（{doc_id}）\n{body[max(0, body.find(start)):][:chars].strip()}"

NUM = re.compile(r"\d+(?:\.\d+)?%?")
EVIDENCE = ("降到", "提升", "证明", "风险", "不足", "建议", "结论", "主导", "负责", "%")

def numbers(text: str) -> list[str]:
    return NUM.findall(text)

def _rule_map(segment: str, max_points: int = 4) -> str:
    sentences = [s.strip(" -•") for s in re.split(r"[。！？\n]", segment) if s.strip()]
    sentences = [s for s in sentences if "面试官：" not in s and "候选人：" not in s and not s.startswith("#")]
    scored = [(2 * len(numbers(s)) + sum(word in s for word in EVIDENCE), s) for s in sentences]
    picked = [s for score, s in sorted(scored, key=lambda item: -item[0]) if score > 0][:max_points]
    if missing := [n for n in numbers(segment) if n not in " ".join(picked)]:  # 数字不能丢
        picked.append("数据：" + "、".join(dict.fromkeys(missing)))
    return "\n".join(f"• {text}" for text in picked)

def _reduce(results: list[str]) -> str:
    bullets = [line for text in results for line in text.splitlines() if line.strip()]
    data_lines = [b for b in bullets if b.startswith("• 数据：")]
    points, seen = [], set()
    for bullet in bullets:
        if bullet not in data_lines and bullet[:26] not in seen:
            seen.add(bullet[:26])
            points.append(bullet)
    return "\n".join(points[:10] + data_lines)

MAP_PROMPT = ChatPromptTemplate.from_messages([("system", "从面试记录中抽取最多 4 条要点，每条必须带数字或证据。"),
                                              ("human", "{segment}")])
MAP_LLM = MockChatModel(script=lambda messages, tools: {"content": _rule_map(str(messages[-1].content))})
MAP, REDUCE = MAP_PROMPT | MAP_LLM, RunnableLambda(_reduce)

def summarize_notes(notes: str, segment_chars: int = 800) -> tuple[str, dict]:
    segments = RecursiveCharacterTextSplitter(chunk_size=segment_chars, chunk_overlap=0).split_text(notes)
    mapped = MAP.batch([{"segment": segment} for segment in segments])
    summary = REDUCE.invoke([str(message.content) for message in mapped])
    missing = [n for n in dict.fromkeys(numbers(notes)) if n not in set(numbers(summary))]
    if missing:  # 最后的兜底：任何遗漏的数字单列，不允许在压缩里蒸发
        summary += "\n• 数字回查补充：" + "、".join(missing)
    report = {"before_tokens": estimate_tokens(notes), "after_tokens": estimate_tokens(summary),
              "segments": len(segments), "llm_calls": len(MAP_LLM.calls), "numbers_total": len(set(numbers(notes))),
              "numbers_kept": len(set(numbers(notes)) & set(numbers(summary)))}
    return summary, report

def count_tokens(messages: list[BaseMessage]) -> int:
    return sum(estimate_tokens(str(message.content)) for message in messages)

def prompt_tokens(messages: list[BaseMessage]) -> int:
    return count_tokens(messages) + 4 * len(messages)  # 每条消息的角色/分隔符开销

SPLITTER = RecursiveCharacterTextSplitter(chunk_size=80, chunk_overlap=0)
PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system}\n\n## 记忆\n{memory}\n\n## 知识\n{knowledge}"),
    ("placeholder", "{history}"),
    ("human", "{question}"),
])
ASSEMBLE = RunnableLambda(lambda values: PROMPT.format_messages(**values))
class ContextBuilder:
    """五类内容先按配额用 trim_messages 截断，超总预算再按优先级丢/压。"""

    def __init__(self, total_tokens: int = 2000) -> None:
        self.total, self.parts = total_tokens, []

    def add(self, name: str, text: str, priority: int, quota: int) -> "ContextBuilder":
        self.parts.append((name, text, priority, quota))
        return self

    def _fit(self, text: str, quota: int) -> str:
        if not text or quota <= 0:
            return ""
        kept = trim_messages([HumanMessage(text)], max_tokens=quota, token_counter=count_tokens,
                             strategy="last", allow_partial=True, text_splitter=SPLITTER.split_text)
        return str(kept[0].content) if kept else ""

    def build(self, question: str) -> tuple[list[BaseMessage], list[list], int]:
        parts = [part for part in self.parts if part[0] != "question"] + [("question", question, 60, 160)]
        rows: list[list] = []
        texts: dict[str, str] = {}
        for name, text, priority, quota in parts:
            kept = self._fit(text, quota)
            texts[name] = kept
            rows.append([name, priority, quota, count_tokens([HumanMessage(text)]), count_tokens([HumanMessage(kept)]),
                         "配额内" if kept == text else ("按配额截断" if kept else "整段丢弃")])
        def assemble() -> list[BaseMessage]:
            return ASSEMBLE.invoke({**texts, "history": [HumanMessage(line) for line in texts["history"].split("\n") if line.strip()]})
        for _ in range(8):
            messages = assemble()
            used = prompt_tokens(messages)
            if used <= self.total:
                break
            row = min((item for item in rows if item[0] != "question" and texts[item[0]]), key=lambda item: item[1])
            target = row[4] - (used - self.total)
            texts[row[0]] = "" if target < max(24, row[4] * 0.3) else self._fit(texts[row[0]], target)
            row[4] = count_tokens([HumanMessage(texts[row[0]])])
            row[5] = "整段丢弃" if not texts[row[0]] else "压缩到剩余额度"
        messages = assemble()
        return messages, rows, prompt_tokens(messages)

def print_report(rows: list[list], actual: int, budget: int) -> None:
    print(f"{'片段':<10}{'优先级':>6}{'配额':>7}{'原始':>7}{'实际':>7}  处理")
    for name, priority, quota, before, after, action in rows:
        print(f"{name:<10}{priority:>8}{quota:>8}{before:>8}{after:>8}  {action}")
    print(f"合计 {actual} token / 预算 {budget}，{'未超' if actual <= budget else '已超'}")
POSITION_WEIGHT = {"开头": 0.95, "中间": 0.18, "结尾": 0.72}  # 模拟 lost-in-the-middle

def lost_in_middle(needle: str, filler: str) -> list[tuple[str, float]]:
    results = []
    for position, weight in POSITION_WEIGHT.items():
        if position == "开头":
            context = needle + filler
        elif position == "结尾":
            context = filler + needle
        else:
            context = filler[: len(filler) // 2] + needle + filler[len(filler) // 2 :]
        results.append((position, weight if needle in context else 0.0))
    return results
def main() -> None:
    print("=== 1. 素材：6000 字面试逐字稿 + 制度 + 记忆 + 历史 ===")
    notes = build_transcript()
    print(f"逐字稿 {len(notes)} 字，估算 {estimate_tokens(notes)} token")
    knowledge = "\n\n".join([policy_excerpt("leave-2025", "### 2.2", 280),
                             policy_excerpt("leave-2025", "### 2.3", 260),
                             policy_excerpt("privacy-2025", "## 1. 数据分级", 240)])
    memory = ("员工：张伟（E1001，技术部，上海）。\n偏好：结论先行；所有结论必须附制度条款；不接受电话打扰。\n"
              "历史：上周确认年假 15 天已休 2 天；年假最多结转 5 天至次年 3 月 31 日；本次是招聘场景，"
              "候选人信息属 L2，拼 Prompt 前必须脱敏，只保留与岗位相关的字段。")
    history = "\n".join([f"第 {i} 轮：讨论王浩终面的评估口径、面试官时间与交接期，结论记在评估表第 {i} 栏。" for i in range(1, 13)])
    question = "帮我把王浩的终面记录整理成 5 条结论和 3 个风险点，并给出是否发 P6 offer 的建议。"

    def new_builder(total: int) -> ContextBuilder:
        return (ContextBuilder(total)
                .add("system", "你是 HR 招聘助手，输出必须带证据，缺证据就说不知道。", 50, 200)
                .add("memory", memory, 30, 220).add("knowledge", knowledge, 20, 600)
                .add("history", history, 10, 320))

    print("\n=== 2. 预算 2000 token：五类上下文各就各位 ===")
    _, rows, actual = new_builder(2000).build(question)
    print_report(rows, actual, 2000)
    print("\n=== 3. 预算压到 700 token：先丢历史，再压知识 ===")
    _, rows_tight, actual_tight = new_builder(700).build(question)
    print_report(rows_tight, actual_tight, 700)
    dropped = [row[0] for row in sorted(rows_tight, key=lambda item: item[1]) if row[5] != "配额内"]
    print("裁剪顺序（优先级从低到高）：", " → ".join(dropped) or "无需裁剪")

    print("\n=== 4. map-reduce 压缩逐字稿 ===")
    summary, report = summarize_notes(notes)
    print(f"分段 {report['segments']} 段，map 调用 {report['llm_calls']} 次；压缩 {report['before_tokens']} → "
          f"{report['after_tokens']} token，保留数字 {report['numbers_kept']}/{report['numbers_total']}")
    print("摘要前 6 行：\n" + "\n".join(summary.splitlines()[:6]))

    print("\n=== 5. 中间遗忘：同一条款放不同位置 ===")
    needle = "【关键条款】2025 版年假最多结转 5 天至次年 3 月 31 日。"
    filler = "面试官：请介绍项目背景。" * 120
    for position, score in lost_in_middle(needle, filler):
        print(f"  放在{position:<2}：模型注意力权重 {score:.2f}")

    assert actual <= 2000 and actual_tight <= 700
    assert next(row for row in rows_tight if row[0] == "history")[5] == "整段丢弃"
    assert report["numbers_kept"] == report["numbers_total"] and report["after_tokens"] < report["before_tokens"] * 0.35
    scores = dict(lost_in_middle(needle, filler))
    assert scores["中间"] < scores["开头"] and scores["中间"] < scores["结尾"]
    print("\n全部断言通过：trim_messages 预算生效、数字零丢失、中间位置最容易被忽略。")
if __name__ == "__main__":
    main()
