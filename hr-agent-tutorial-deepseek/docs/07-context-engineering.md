---
title: "07 | Context Engineering：上下文预算与压缩"
slug: "context-engineering"
order: 7
part: "单 Agent 核心"
minutes: 60
difficulty: "进阶"
prerequisites: ["06"]
summary: "给六类上下文分配 token 配额，超限按优先级裁剪，并用 map-reduce 压缩长面试记录。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`trim_messages`、`ChatPromptTemplate`、`RunnableLambda`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch07_context.py`。


## 0. 本章你会得到什么

学完这一章，你应该能：

1. 画出一次请求的上下文组成：系统提示、工具、记忆、知识、历史、当前问题。
2. 给每一类上下文定配额，并在总量超限时按优先级「先丢谁、后压谁」。
3. 用 map-reduce 把 6000 字面试记录压成十条要点，同时保证数字和证据一个不丢。
4. 解释「中间遗忘」（lost in the middle）：为什么关键条款明明在上下文里，模型却没用上。
5. 算清一次请求的真实 token 账，知道钱花在哪、延迟卡在哪。

## 1. 场景：一份 6000 字面试记录，塞不进一次请求

11 月 16 日上午 10 点，王浩（候选人 `C003`）来终面，岗位是算法工程师，面试官是孙悦和徐明。40 分钟后，录音转写导出了一份 6200 字的逐字稿：自我介绍、RAG 链路、切片策略、召回评估、幻觉治理、工程实现、离职动机、薪资期望，全在里面。

HR 招聘专员小李要做的事很具体：下午 3 点前把这份记录整理成 5 条结论和 3 个风险点，附上证据，交给用人部门决定是否发 P6 offer。她想让助手一次完成，于是把能想到的材料都塞了进去：

- 系统提示：告诉助手「输出必须带证据」。
- 3 个工具描述：查候选人、查面试官空闲、提交评估。
- 记忆：王浩的岗位、上次沟通的薪资带宽、交接期。
- 制度：年假结转、请假流程、数据分级，共 3 段。
- 历史：过去 10 轮关于面试安排的对话。
- 当前问题：整理结论与风险。

看起来很合理，但一算账就出问题：仅逐字稿就约 4800 token，加上制度、工具、历史，轻松超过 5000 token。这还只是一次请求；如果为了「更全面」把 5 份制度全文、20 轮历史都带上，token 会翻倍，费用和延迟一起涨。

更麻烦的是另一类失败：钱花了、窗口没超，答案却漏了关键信息。孙悦在面试里明确说过「候选人期望 45k 超过 P6 带宽上限，需要 HR 总监特批」，这句话在逐字稿的中段。模型回答「薪资在带宽内，可以直接发 offer」——它读到了开头和结尾，却把中间那句忽略了。这不是模型「没看见」，而是「看见了但没重视」，学术界管这个现象叫 **lost in the middle（中间遗忘）**。

所以本章要解决两个问题，一个关于钱，一个关于质量：

- **预算**：每一类上下文该分多少 token？超了先砍谁？
- **压缩**：长文本怎么压成短文本，还能保住数字和证据？

## 2. 概念：上下文是一份有配额的预算表

先把「上下文」这个词说清楚。**上下文（Context）** 就是这一次请求里，你发给模型的全部内容：系统提示、工具定义、检索到的知识、历史对话、用户问题，全都算。模型没有「记忆」，它只能看到你这次给它的东西。

**上下文窗口（Context Window）** 是模型一次最多能接收多少 token。**Token** 是模型计费和计长的最小单位，中文大约 1 个字 1 个 token，英文大约 4 个字符 1 个 token（本教程统一用 `estimate_tokens` 估算）。

窗口大不等于效果好。窗口是「能装多少」，有效注意力是「真正用上多少」。经验规律是：关键信息放在开头和结尾，模型更容易用上；放在中间，容易被稀释。这就是为什么「把所有资料都塞进去」是个坏策略——你付了 token 的钱，却买不到对应的注意力。

### 2.1 六类上下文与优先级

本章把上下文拆成六块，每块有独立配额和优先级：

| 片段 | 放什么 | 优先级 | 默认配额 | 超限时 |
| --- | --- | --- | --- | --- |
| system | 角色、边界、输出格式 | 50 | 200 | 最后压 |
| tools | 工具名、描述、参数 schema | 40 | 260 | 尽量保 |
| memory | 画像、偏好、历史结论 | 30 | 200 | 可压 |
| knowledge | 制度、条款、证据 | 20 | 500 | 先压 |
| history | 最近若干轮对话 | 10 | 300 | 最先丢 |
| question | 当前问题 | 60 | 160 | 永不丢 |

优先级数字越大越不能删。为什么是这个顺序？

- **question 最高**：问题是这次请求的目的，丢了就什么都没意义。
- **system 次高**：角色和边界决定了回答的安全性与格式，不能为了省 token 把它压没。
- **tools 较高**：工具描述没了，模型就不知道能调什么，等于砍掉手脚。
- **memory 中等**：画像让回答个性化，但缺了也能答，只是差一点。
- **knowledge 较低**：知识可以压缩、可以只留最相关的两段，甚至可以让模型先说「需要更多信息」。
- **history 最低**：历史是「锦上添花」，而且往往最长、最冗余，所以第一个牺牲。

这套顺序不是绝对的。做合同审查时 knowledge 会比 memory 重要；做多轮排期时 history 可能比 tools 重要。**优先级要按业务定，不能照抄**。

### 2.2 三种压缩手段

超预算时，除了「丢」，还有两种更聪明的做法：

1. **裁剪（truncate）**：直接截断，保留开头。便宜、无损于代码、但会丢尾部信息。适合历史、日志。
2. **摘要（summarize）**：让模型把长文压成要点。贵一点、慢一点，但能保住语义。适合面试记录、会议纪要。
3. **检索（retrieve）**：不全量给，只给最相关的片段。第 08 章会专门讲。

本章三种都会用到：历史用裁剪，逐字稿用摘要，知识用「按配额截断 + 只取相关段落」。

### 2.3 中间遗忘与引用锚点

用一个简化模型说明「中间遗忘」。假设模型对上下文不同位置的注意力权重是：

```text
注意力权重
1.0 ┤ ███                                     ███
0.8 ┤ ███                                     ███
0.6 ┤ ███                                     ███
0.4 ┤ ███                                     ███
0.2 ┤ ███            ███                      ███
0.0 └─┬──────────────┬────────────────────────┬─────▶ 位置
     开头            中间                      结尾
      0.95           0.18                     0.72
```

同一条「最多结转 5 天」的条款，放在开头命中率 0.95，放中间只有 0.18，放结尾 0.72。这不是模型厂商的 bug，而是训练数据和使用方式的共同结果。工程上的应对有三条：

- 关键约束放**开头或结尾**，不要埋在中间。
- 长文先**压缩或检索**，别让中间堆满无关内容。
- 让模型**先引用再回答**：要求它输出「依据第几条」，引用位置本身就是一个锚点，能把注意力拉回证据。

> 💡 **小白提示**：不要被「上下文工程」这个名字吓到。它本质上就是「一次请求里放什么、放多少、放哪里」三个问题。你写周报时也会做同样的事：先写结论，再放证据，附件太长就摘录。

## 3. 动手：ContextBuilder 与 map-reduce

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


在仓库根目录执行：

```powershell
python code/ch07_context.py
```

完整代码（与 `code/ch07_context.py` 一致）：

```python
"""第 07 章：Context Engineering —— 给上下文做预算、裁剪与压缩。

三件事：按优先级做上下文预算；用 map-reduce 压缩 6000 字逐字稿；复现「中间遗忘」。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import all_policy_documents, load_text
from common.llm import MockLLM, system, tool_schema, user
from common.text import chunk_text, estimate_tokens, messages_tokens, truncate_tokens

PROBES = [("RAG", "你们的 RAG 链路具体怎么搭的？"), ("切片", "切片策略怎么定的，为什么是 400 到 600 字？"),
          ("评估", "召回效果你们怎么评估？"), ("背景", "先介绍下你的背景，重点讲最近两年。")]
OPENERS = ["我先给结论。", "这块我踩过坑，说具体点。", "分两层讲。"]
TAILS = ["当时我们把评估口径先固定下来，每次改动都跑同一套数据，避免拍脑袋。",
         "这件事我负责方案设计和验收标准，上线前跑了三轮对照实验。",
         "我们的原则是宁可多问一句，也不让用户拿到没出处的答案。"]

# 把 C003 的结构化记录展开成约 6000 字逐字稿（模拟 ASR 转写，内容全部虚构）
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
    index = doc["content"].find(start)
    return f"《{doc['title']}》v{doc['version']}（{doc_id}）\n{doc['content'][index if index >= 0 else 0 :][:chars].strip()}"

NUM = re.compile(r"\d+(?:\.\d+)?%?")
EVIDENCE = ("降到", "提升", "证明", "风险", "不足", "建议", "结论", "主导", "负责", "%")

def numbers(text: str) -> list[str]:
    return NUM.findall(text)

def _rule_map(segment: str, max_points: int = 4) -> str:
    """map 阶段：按「含数字/证据词」打分挑句子，缺的数字补在末尾。"""
    sentences = [s.strip(" -•") for s in re.split(r"[。！？\n]", segment) if s.strip()]
    sentences = [s for s in sentences if "面试官：" not in s and "候选人：" not in s and not s.startswith("#")]
    scored = [(2 * len(numbers(s)) + sum(word in s for word in EVIDENCE), s) for s in sentences]
    picked = [s for score, s in sorted(scored, key=lambda item: -item[0]) if score > 0][:max_points]
    missing = [n for n in numbers(segment) if n not in " ".join(picked)]
    if missing:  # 数字是证据的骨架，压缩时可以丢修饰词，不能丢数字
        picked.append("数据：" + "、".join(dict.fromkeys(missing)))
    return "\n".join(f"• {text}" for text in picked)

def summarize_notes(notes: str, segment_chars: int = 800, max_bullets: int = 10) -> tuple[str, dict]:
    """map-reduce：分段摘要（过模型）→ 合并去重（规则）→ 数字回查。"""
    llm = MockLLM(lambda messages, tools: {"content": _rule_map(messages[-1]["content"])})
    segments = chunk_text(notes, chunk_size=segment_chars, overlap=0)
    mapped = [llm.chat([system("抽取要点，保留数字与证据"), user(seg)]) for seg in segments]
    bullets = [line for resp in mapped for line in (resp.content or "").splitlines() if line.strip()]
    data_lines = [b for b in bullets if b.startswith("• 数据：")]
    points, seen = [], set()
    for bullet in bullets:
        if bullet in data_lines or bullet[:26] in seen:
            continue
        seen.add(bullet[:26])
        points.append(bullet)
    summary = "\n".join(points[:max_bullets] + data_lines)
    missing = [n for n in dict.fromkeys(numbers(notes)) if n not in set(numbers(summary))]
    if missing:  # 最后的兜底：任何遗漏的数字单列，不允许在压缩里蒸发
        summary += "\n• 数字回查补充：" + "、".join(missing)
    report = {"before_tokens": estimate_tokens(notes), "after_tokens": estimate_tokens(summary),
              "segments": len(segments), "llm_calls": len(llm.calls),
              "numbers_total": len(set(numbers(notes))),
              "numbers_kept": len(set(numbers(notes)) & set(numbers(summary)))}
    return summary, report

@dataclass
class Row:
    name: str
    priority: int
    quota: int
    before: int
    after: int
    action: str

class ContextBuilder:
    """按配额装填，超总量时从优先级最低的开始丢或压。"""

    def __init__(self, total_tokens: int = 2000) -> None:
        self.total = total_tokens
        self.parts: list[tuple[str, str, int, int]] = []  # (名字, 文本, 优先级, 配额)

    def add(self, name: str, text: str, priority: int, quota: int) -> "ContextBuilder":
        self.parts.append((name, text, priority, quota))
        return self

    def build(self, question: str) -> tuple[list[dict], list[Row], int]:
        self.parts = [part for part in self.parts if part[0] != "question"]
        self.add("question", question, 60, 160)
        rows: list[Row] = []
        texts: dict[str, str] = {}
        for name, text, priority, quota in self.parts:
            capped = truncate_tokens(text, quota)
            texts[name] = capped
            rows.append(Row(name, priority, quota, estimate_tokens(text), estimate_tokens(capped),
                            "配额内" if capped == text else "按配额截断"))

        def assemble() -> list[dict]:
            sections = [f"## {row.name}\n{texts[row.name]}" for row in rows
                        if texts.get(row.name) and row.name != "history"]
            messages = [system("\n\n".join(sections))]
            if texts.get("history"):
                messages += [{"role": "user" if i % 2 == 0 else "assistant", "content": line}
                             for i, line in enumerate(texts["history"].split("\n")) if line.strip()]
            return messages + [user(question)]

        for row in sorted(rows, key=lambda item: item.priority):  # 先丢历史，再压知识、记忆
            if row.name == "question" or messages_tokens(assemble()) <= self.total:
                continue
            over = messages_tokens(assemble()) - self.total
            texts[row.name] = truncate_tokens(texts[row.name], max(0, row.after - over))
            row.after = estimate_tokens(texts[row.name])
            row.action = "整段丢弃" if not texts[row.name] else "压缩到剩余额度"
        return assemble(), rows, messages_tokens(assemble())

def print_report(rows: list[Row], actual: int, budget: int) -> None:
    print(f"{'片段':<10}{'优先级':>6}{'配额':>7}{'原始':>7}{'实际':>7}  处理")
    for row in rows:
        print(f"{row.name:<10}{row.priority:>8}{row.quota:>8}{row.before:>8}{row.after:>8}  {row.action}")
    print(f"合计 {actual} token / 预算 {budget}，{'未超' if actual <= budget else '已超'}")

POSITION_WEIGHT = {"开头": 0.95, "中间": 0.18, "结尾": 0.72}  # 模拟 lost-in-the-middle

def lost_in_middle(needle: str, filler: str) -> list[tuple[str, float]]:
    """把同一句关键条款放在长上下文的不同位置，看模型「用上它」的概率。"""
    results = []
    for position, weight in POSITION_WEIGHT.items():
        if position == "开头":
            context = needle + filler
        elif position == "结尾":
            context = filler + needle
        else:
            half = filler[: len(filler) // 2]
            context = half + needle + filler[len(filler) // 2 :]
        # 条款确实在上下文里（检索没问题）≠ 模型会用它（注意力问题）
        results.append((position, weight if needle in context else 0.0))
    return results

def main() -> None:
    print("=== 1. 素材：一份 40 分钟面试逐字稿 + 制度 + 历史 ===")
    notes = build_transcript()
    print(f"逐字稿 {len(notes)} 字，估算 {estimate_tokens(notes)} token")
    knowledge = "\n\n".join([policy_excerpt("leave-2025", "### 2.2", 280),
                             policy_excerpt("leave-2025", "### 2.3", 260),
                             policy_excerpt("privacy-2025", "## 1. 数据分级", 240)])
    memory = "员工：张伟（E1001，技术部，上海）；上次问过年假结转；偏好书面确认。"
    history = "\n".join(["候选人王浩的终面约在 11-16 10:00。", "面试官是孙悦和徐明，预计 40 分钟。",
                         "请重点确认 RAG 评估方法和交接期。", "薪资带宽 P6 上限 45k，需 HR 总监审批。",
                         "面完 24 小时内要交评估表。", "交叉面安排在 11-18 下午。"])
    tools = json.dumps([tool_schema("get_candidate", "查询候选人", {"candidate_id": {"type": "string"}}),
                        tool_schema("get_interview_slots", "查面试官空闲", {"interviewer": {"type": "string"}}),
                        tool_schema("create_evaluation", "提交面试评估",
                                    {"candidate_id": {"type": "string"}, "score": {"type": "number"}})],
                       ensure_ascii=False)
    question = "帮我把王浩的终面记录整理成 5 条结论和 3 个风险点，并给出是否发 P6 offer 的建议。"

    def new_builder(total: int) -> ContextBuilder:
        return (ContextBuilder(total)
                .add("system", "你是 HR 招聘助手，输出必须带证据，缺证据就说不知道。", 50, 200)
                .add("tools", tools, 40, 260).add("memory", memory, 30, 200)
                .add("knowledge", knowledge, 20, 500).add("history", history, 10, 300))

    print("\n=== 2. 预算 2000 token：六类上下文各就各位 ===")
    messages, rows, actual = new_builder(2000).build(question)
    print_report(rows, actual, 2000)
    print("\n=== 3. 预算压到 800 token：看看先牺牲谁 ===")
    _, rows_tight, actual_tight = new_builder(800).build(question)
    print_report(rows_tight, actual_tight, 800)
    print("\n=== 4. map-reduce 压缩逐字稿 ===")
    summary, report = summarize_notes(notes)
    print(f"分段 {report['segments']} 段，调用模型 {report['llm_calls']} 次；压缩 "
          f"{report['before_tokens']} → {report['after_tokens']} token，"
          f"保留数字 {report['numbers_kept']}/{report['numbers_total']}")
    print("摘要前 6 行：\n" + "\n".join(summary.splitlines()[:6]))
    print("\n=== 5. 中间遗忘：同一条款放不同位置 ===")
    needle = "【关键条款】2025 版年假最多结转 5 天至次年 3 月 31 日。"
    filler = "面试官：请介绍项目背景。" * 120
    for position, score in lost_in_middle(needle, filler):
        print(f"  放在{position:<2}：模型注意力权重 {score:.2f}")

    assert actual <= 2000 and actual_tight <= 800
    assert next(row for row in rows_tight if row.name == "history").action == "整段丢弃"
    assert report["numbers_kept"] == report["numbers_total"] and report["after_tokens"] < report["before_tokens"] * 0.35
    scores = dict(lost_in_middle(needle, filler))
    assert scores["中间"] < scores["开头"] and scores["中间"] < scores["结尾"]
    print("\n全部断言通过：预算生效、数字零丢失、中间位置最容易被忽略。")

if __name__ == "__main__":
    main()
```

运行结果（节选）：

```text
=== 2. 预算 2000 token：六类上下文各就各位 ===
片段           优先级     配额     原始     实际  处理
system          50     200      23      23  配额内
tools           40     260     163     163  配额内
memory          30     200      27      27  配额内
knowledge       20     500     585     500  按配额截断
history         10     300      80      80  配额内
question        60     160      35      35  配额内
合计 910 token / 预算 2000，未超

=== 3. 预算压到 800 token：看看先牺牲谁 ===
片段           优先级     配额     原始     实际  处理
system          50     200      23      23  配额内
tools           40     260     163     163  配额内
memory          30     200      27      27  配额内
knowledge       20     500     585     495  压缩到剩余额度
history         10     300      80       0  整段丢弃
question        60     160      35      35  配额内
合计 800 token / 预算 800，未超

=== 4. map-reduce 压缩逐字稿 ===
分段 8 段，调用模型 8 次；压缩 4793 → 212 token，保留数字 14/14
摘要前 6 行：
• 召回评估：自建 200 条 Golden Case，Recall@5 从 62% 提升到 88%，引用准确率 91%
• 时间：2026-11-16 ｜ 时长：40 分钟
• 切片策略：按标题层级 + 语义段落，chunk 400–600 字，重叠 15%；对表格单独处理
• 工程：用 Milvus + BM25 混合检索，Redis 缓存，异步索引；了解 vLLM 部署
• 这件事我负责方案设计和验收标准，上线前跑了三轮对照实验
• 工程：用 Milvus + BM25

=== 5. 中间遗忘：同一条款放不同位置 ===
  放在开头：模型注意力权重 0.95
  放在中间：模型注意力权重 0.18
  放在结尾：模型注意力权重 0.72
```

读这张预算表，重点看三处：

1. **2000 预算下，实际只用了 910 token**。预算不是必须花完，它是上限。真正健康的系统往往只用到一半，把余量留给变化。
2. **知识片段 585 token，配额 500，被截掉 85**。它优先级低于工具，所以先被压。如果这条知识是「签约前必须核验离职证明」这种硬约束，就不该只给 500，而要单独提优先级。
3. **压到 800 时，历史被整段丢弃，知识从 585 压到 495**。注意：历史和知识的「牺牲顺序」是由优先级决定的，不是由谁更长决定的。

> 🧪 **动手**：把 `new_builder(800)` 改成 `new_builder(500)`，再跑一次。你会看到历史仍然被整段丢弃，但工具还完整；继续压到 250，工具才开始被截断，system 和 question 始终保住。这说明预算不是越小越「省」，而是有一个下限——低于下限，模型就不知道自己要干什么了。

## 4. 逐行拆解

### 4.1 配额只是第一道闸，总量才是硬约束

`build()` 的第一段做的是「按配额截断」：

```python
capped = truncate_tokens(text, quota)
```

每类上下文先被自己的配额卡一次。但配额之和可能仍然超过总预算，所以第二段要做「按优先级丢」：

```python
for row in sorted(rows, key=lambda item: item.priority):
    if row.name == "question" or messages_tokens(assemble()) <= self.total:
        continue
```

这里有个容易写错的细节：判断「超没超」必须用 `messages_tokens(assemble())` 真实组装后的 token，而不是把各段估算值一加。因为消息有角色标记开销、段落标题开销、历史变成多条消息后每条都要加 4 token 左右。差几十 token，在 800 的预算下就是致命的。

### 4.2 为什么先丢历史

排序键是 `priority` 升序，所以历史（10）排第一。丢了历史意味着多轮对话的连贯性变差，但问题、系统提示、工具都还在，模型仍然能回答。反过来，如果先丢 system，模型可能忘记「只能依据证据回答」，开始编造。**丢东西的顺序，本质上是在选择「哪种错误更可接受」**。

还有一个隐含约束：单段压缩不能压到「半句话」。`truncate_tokens` 会保留开头并加省略号，这意味着压缩后的知识片段可能只剩半条制度。生产上更稳的做法是「整段留或整段丢」，或者按条款边界压，而不是按字符数切。

### 4.3 map 阶段：先挑句子，再补数字

`_rule_map` 是整个压缩里最像「人」的部分：

```python
scored = [(2 * len(numbers(s)) + sum(word in s for word in EVIDENCE), s) for s in sentences]
picked = [s for score, s in sorted(scored, key=lambda item: -item[0]) if score > 0][:max_points]
```

给每个句子打分：出现一个数字加 2 分，出现一个证据词（「降到」「提升」「风险」「结论」……）加 1 分。分高的先选，最多选 4 句。然后关键一步：

```python
missing = [n for n in numbers(segment) if n not in " ".join(picked)]
if missing:
    picked.append("数据：" + "、".join(dict.fromkeys(missing)))
```

所有没被选中的数字，单独拼成一行「数据：……」。这行的语义很弱，但它是**证据台账**：只要数字在，人就还能顺着数字回去查原文。这正是「压缩可以丢修辞，不能丢证据」的工程实现。

真实项目里，map 阶段通常是让模型输出结构化 JSON（结论、证据、数字、风险），而不是规则打分。但无论用模型还是规则，都要保留「数字回查」这一步——模型摘要最容易丢的就是数字。

### 4.4 reduce 阶段：去重、限量、再查一遍

reduce 做三件事：

1. **去重**：用每条要点的前 26 个字符当指纹，重复的丢掉。
2. **限量**：最多保留 10 条普通要点，但「数据：」行不占这 10 条名额。
3. **数字回查**：合并完再扫一遍原文数字，缺的补在「数字回查补充」里。

为什么限量还要单独给数据行开口子？因为数字是事实，要点是观点。观点可以少，事实不能丢。这也是压缩策略和普通摘要的区别：普通摘要追求「短」，上下文压缩追求「短且可验证」。

### 4.5 中间遗忘实验的意义与局限

`lost_in_middle` 里的 `POSITION_WEIGHT` 是一个**模拟**，不是真实测量：

```python
POSITION_WEIGHT = {"开头": 0.95, "中间": 0.18, "结尾": 0.72}
```

它想表达的是「同一句话，放在不同位置，被模型用上的概率不同」。真实模型的具体数值会随模型、任务、语言变化，但「中间最弱」这个趋势在多篇研究和工程实践里反复出现。所以这个实验的正确用法是：

- 用它建立直觉：关键条款别埋中间。
- 用它做设计约束：把最重要的证据放在 Prompt 开头或结尾。
- **不要**把它当成某个模型的准确指标去写进 SLA。

## 5. 实验：把预算和压缩推到边界

### 实验一：预算从 800 调到 500，再调到 250

把第 3 节的 `new_builder(800)` 改成 `new_builder(500)`。预期现象：历史仍然是整段丢弃，知识从 495 被压到约 200，工具和 system 还没动。再改成 `new_builder(250)`：知识先被压到几乎为零，工具开始被截断（163 降到约 117），system 和 question 仍然保住。这说明优先级只有在**极端预算**下才真正发挥作用；预算略紧时，系统会先牺牲最长的那块，而不是优先级最低的那块——因为「压缩」比「丢弃」更划算。

### 实验二：分段大小从 800 改成 1600

把 `summarize_notes(notes)` 改成 `summarize_notes(notes, segment_chars=1600)`。预期现象：分段数从 8 降到 4，模型调用次数减半，但每段更长、map 阶段丢的信息更多，摘要的颗粒度变粗。对比两次的 `after_tokens` 和摘要内容，你会看到「调用次数」和「摘要质量」的取舍。

### 实验三：把摘要上限从 10 条改成 3 条

把 `summarize_notes(notes)` 改成 `summarize_notes(notes, max_bullets=3)`。预期现象：普通要点只剩 3 条，但「数据：」行和「数字回查补充」仍然保留，`numbers_kept` 依然是 14/14。这验证了「观点可减、证据不可减」的设计。

### 实验四：把关键条款放到中间

直接看第 5 节输出里「放在中间」那一行：`needle` 确实在上下文里（`needle in context` 为真），但权重只有 0.18。这说明「检索到了」和「模型用上了」是两件事，评测时不能只看召回率。想更直观，可以把 `filler` 换成一段更长的无关文本，让中间位置被稀释得更彻底。

> ⚠️ **生产提醒**：不要在线上用字符数估算 token 做硬预算。中文、英文、代码、emoji 的折算比例不同，`estimate_tokens` 只适合教学和离线估算。生产要么用模型厂商的 tokenizer（如 `tiktoken`），要么直接读返回的 `usage.prompt_tokens`，并留 10%~20% 的安全余量。

## 6. 工程化视角

本章的 `ContextBuilder` 是一个「能跑」的骨架，上生产还要补五件事：

**真实 token 计量。** 用 `tiktoken` 或厂商 SDK 的计数接口；对工具 schema、消息角色开销单独建模。预算表要按模型维护，而不是写死一个数字。

**缓存友好的排列。** 大多数模型服务对「相同前缀」有缓存折扣。把稳定内容（系统提示、工具定义、制度）放前面，把变化内容（历史、当前问题）放后面，能显著降本。反过来，每次把历史插到系统提示前面，会让缓存全部失效。

**结构化压缩。** 面试记录的理想压缩不是自由文本，而是固定 schema：`{candidate_id, conclusions: [{text, evidence}], risks: [{text, severity, evidence}], missing_info: []}`。结构化输出可以直接入库、可以做校验、可以失败重试。

**压缩后校验。** 至少做三件事：数字是否齐全、引用是否还在、结论是否与原文矛盾。本章用断言做了前两件；第三件需要 LLM-as-judge 或人工抽检，第 15 章会讲。

**权限与脱敏。** 面试记录属于 L2 内部数据，要按最小权限只给有招聘权限的角色。拼 Prompt 前先按角色过滤字段，手机号、邮箱、身份证号用 `mask_pii` 打码；不要把整份记录直接塞给一个通用问答入口。

> ⚠️ **生产提醒**：预算要同时管输入和输出。很多团队只算 Prompt 的 token，忘了给 `max_tokens` 设上限，结果模型一次生成 3000 字，费用比输入还高。输入预算、输出上限、总成本上限，三个都要有。

## 7. 常见坑

**坑 1：把「窗口没超」当成「上下文没问题」。**
现象：请求成功返回，但答案漏了中段的关键约束。
原因：只做了容量管理，没做注意力管理。
解法：关键条款放两端；长文先压缩；要求模型引用证据。

**坑 2：所有片段平均分配预算。**
现象：历史占了 60%，知识和工具被压得只剩骨架。
原因：配额是拍脑袋定的，没有按业务优先级。
解法：按「缺了会怎样」排序，question 和 system 优先，history 最后。

**坑 3：摘要只写结论，丢掉数字和出处。**
现象：摘要读起来很顺，但没法验证，也没法回答「具体几天」。
原因：把摘要当成了给人看的周报。
解法：结构化摘要 + 数字回查 + 引用锚点。

**坑 4：压缩后不做校验。**
现象：摘要说「通过」，原文其实是「待定」；数字从 62% 变成 68%。
原因：生成式压缩天然会漂移。
解法：断言 + 抽样人工复核 + 关键字段回查原文。

**坑 5：每次请求都重新排列上下文。**
现象：账单比预期高，缓存命中率很低。
原因：稳定前缀被变化内容打断。
解法：固定顺序：system → tools → knowledge → memory → history → question。

**坑 6：忽略工具 schema 的 token 成本。**
现象：只注册了 10 个工具，上下文就少了 1000 token。
原因：每个工具的描述和参数 schema 都算 token，且很难压缩。
解法：工具按场景分组，只挂当前任务需要的；描述写短，参数用枚举。

## 8. 练习

### 练习 1（易）：算一笔真实的账

假设模型输入价格是每百万 token 15 元，输出每百万 token 60 元。一次请求输入 4800 token、输出 500 token，跑 1000 次要多少钱？如果压缩后输入降到 1500 token，省了多少？

<details><summary>参考答案</summary>

压缩前：输入 `4800 × 1000 = 4.8M` token，费用 `4.8 × 15 = 72` 元；输出 `500 × 1000 = 0.5M`，费用 `0.5 × 60 = 30` 元；合计 102 元。

压缩后：输入 `1500 × 1000 = 1.5M`，费用 22.5 元；输出假设不变 30 元；合计 52.5 元。省了 49.5 元，约 48%。

注意：压缩本身也要调模型（本章 8 次 map 调用），如果压缩是每次请求都做，成本要算进去；更常见的做法是「离线压缩一次，结果缓存复用」。

</details>

### 练习 2（中）：给知识片段加「整段保留」开关

现在 `truncate_tokens` 会把知识片段截成半句话。请给 `add()` 增加一个 `keep_whole: bool` 参数，为 `True` 时要么整段保留、要么整段丢弃。

<details><summary>参考答案</summary>

```python
def add(self, name, text, priority, quota, keep_whole=False):
    self.parts.append((name, text, priority, quota, keep_whole))
```

在 `build()` 里：

```python
if keep_whole and estimate_tokens(text) > quota:
    capped = ""            # 放不下就整段不要
elif keep_whole:
    capped = text
else:
    capped = truncate_tokens(text, quota)
```

代价是可能浪费配额。更好的做法是按条款边界切分，再按条取舍；这需要知识片段带 `clause_id`，第 08 章会讲。

</details>

### 练习 3（中）：把历史压成「最近 3 轮 + 一句摘要」

现在历史要么全留、要么全丢。请改成：保留最近 3 轮原文，更早的压成一行「早前讨论了 X、Y、Z」。

<details><summary>参考答案</summary>

```python
lines = texts["history"].split("\n")
if len(lines) > 6:
    old, recent = lines[:-6], lines[-6:]
    texts["history"] = "早前讨论：" + "、".join(item[:12] for item in old) + "\n" + "\n".join(recent)
```

注意要点：摘要行也要占 token；压缩后的历史仍然可能超预算，所以要在循环里重新计算。真实系统里更常用「分层摘要」：每 10 轮生成一个块摘要，检索时按相关度取块。

</details>

### 练习 4（难）：用模型做 map，而不是规则

把 `_rule_map` 换成一次真实的 `llm.chat` 调用（MockChatModel 用脚本模拟），要求输出 JSON：`{"points": [...], "numbers": [...]}`，并在 reduce 阶段校验 `numbers` 与原文一致。

<details><summary>参考答案</summary>

```python
def _model_map(segment, llm):
    prompt = (
        "从下面的面试记录中抽取最多 4 条要点，每条必须带数字或证据。"
        "只输出 JSON：{\"points\": [\"...\"], \"numbers\": [\"...\"]}\n\n" + segment
    )
    raw = llm.chat([system("你是严谨的面试记录整理助手"), user(prompt)]).content or "{}"
    data = json.loads(raw)
    return data.get("points", []), data.get("numbers", [])
```

校验：`set(原文数字) - set(data["numbers"])` 必须为空，否则重试一次或把缺失数字补进摘要。注意 JSON 解析失败要有兜底，不能让一个坏样本把整批任务打挂。

</details>

### 练习 5（难）：给预算表加「按模型切换」

不同模型的窗口和价格不同。请让 `ContextBuilder` 接受一个 `model_profile`，包含 `window`、`price_in`、`price_out`，并输出这次请求的预估成本。

<details><summary>参考答案</summary>

```python
PROFILES = {
    "small": {"window": 32000, "price_in": 3, "price_out": 12},
    "large": {"window": 128000, "price_in": 15, "price_out": 60},
}
```

`build()` 里用 `profile["window"]` 作为总预算上限，并用 `tokens / 1_000_000 * price` 算成本。更完整的做法是按任务难度路由：简单问答走 small，长文分析走 large，并在报告里同时打印「本可以走 small 省多少」。这就是第 15 章成本指标的前置。

</details>

## 9. 小结与下一章

三句话记住本章：

1. 上下文是**预算**，不是垃圾桶：六类内容各有配额，超了按优先级丢，question 和 system 最后动。
2. 压缩要**保证据**：map 挑句子、reduce 去重、数字回查，三步缺一不可。
3. 位置影响注意力：关键条款放开头或结尾，长文先压缩再喂，别指望模型自己从中间捞。

到这里，上下文里的「知识」还是我们手写进去的几段制度节选。真实系统里，制度有几十份、上百个版本，不可能手工挑选。下一章进入 RAG：让系统自己从文档库里找出该看的那几段，并且给出可核验的引用。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **trim_messages + ChatPromptTemplate + RunnableLambda**，完整代码见 `code/ch07_context.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain_core.messages import trim_messages
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

history = trim_messages(messages, max_tokens=320, strategy="last",
                        token_counter=count_tokens, start_on="human")
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是 HR 助手。记忆：{memory}"),
    MessagesPlaceholder("history"),
    ("human", "{question}"),
])
chain = prompt | model
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 预算 | `trim_messages` |
| 组装 | `ChatPromptTemplate` |
| map-reduce | `RunnableLambda` / `.batch()` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch07_context.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
