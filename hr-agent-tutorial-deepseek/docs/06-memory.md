---
title: "06 | Memory：让助手记住员工与历史"
slug: "memory"
order: 6
part: "单 Agent 核心"
minutes: 60
difficulty: "进阶"
prerequisites: ["05"]
summary: "用窗口、摘要、画像与事实三层记忆，让 HR 助手跨会话接住「那病假呢」。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`MessagesState`、`InMemorySaver`、`trim_messages`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch06_memory.py`。


## 0. 本章你会得到什么

学完这一章，你应该能：

1. 说清会话窗口、滚动摘要、长期画像、业务事实这四类记忆的区别，以及各自该活多久。
2. 写出一个不依赖向量库的 `MemoryStore`：写入、召回、冲突更新、TTL 过期、越权拦截。
3. 用「关键词重合 + 时间衰减」给记忆打分，并能解释为什么 11 天前的年假记忆仍然排进前三。
4. 画出记忆的读写流程，指出哪里必须做脱敏、最小权限和审计。
5. 判断一条信息到底该不该被长期记住——这比记住本身更重要。

## 1. 场景：一句「那病假呢」暴露的记忆断层

张伟是技术部的后端工程师，工号 `E1001`，2021 年 3 月入职。11 月 5 日，他在 HR 共享服务中心的助手窗口里问了四个问题：年假还剩几天、12 月休 3 天够不够、要提前几天申请、没休完能不能跨年。助手查了余额，告诉他「15 天额度，已休 2 天，还剩 13 天」，又补了一句「最多结转 5 天到次年 3 月 31 日」。张伟说了声谢谢就关了窗口。

11 天后，11 月 16 日，张伟又来了。这次他只打了一行字：

> 那病假呢？

这是一个再普通不过的追问。人跟人说话时，「那」指的是上一轮聊的年假；「病假呢」问的是病假的材料、流程、工资。但对一个没有记忆的助手来说，这行字几乎不可回答：他不知道「那」指什么，不知道张伟是哪个部门的，也不知道张伟上周已经确认过哪些信息。于是最常见的糟糕体验出现了——助手礼貌地反问：「请问您的工号和部门是？您想咨询哪类假期？」

张伟要重复一遍自我介绍，情绪先掉一半。这还只是体验问题。更危险的是另一种失败：某天系统「聪明」过头，把张伟请病假的原因、工资带宽、家庭联系人全部长期记住，并在主管查询「张伟最近状态」时一起召回。病假原因属于医疗信息，在《员工与候选人数据隐私规范》（`HR-PRIVACY-2025`）里是 L3 敏感数据，需要最小必要、审批与审计。一旦被无差别召回，这不是体验问题，是合规事故。

所以本章要解决的不是「怎么让模型记住更多」，而是三个更精确的问题：

- 哪些信息应该留在**当前会话**里，会话结束就清掉？
- 哪些信息应该压成**摘要**跨会话保留，但不能无限长？
- 哪些信息应该沉淀为**长期画像与事实**，同时带上来源、时间、置信度、有效期和密级？

共享服务中心每天有 200 多条重复咨询，其中相当一部分是「上次那个事」的延续。把记忆做对，员工少说三句话，HR 少查两次系统；把记忆做错，轻则答非所问，重则泄露隐私。

## 2. 概念：三层记忆与一次召回

先打个比方。你处理员工咨询时，脑子里其实有三层东西：

- **工作记忆**：刚才这十分钟聊了什么，他说「那病假呢」你知道「那」指年假。这层容量很小，聊完就淡了。
- **便签**：你把「张伟 12 月想休 3 天」写在便利贴上，贴在本子第一页。下次他再来，你扫一眼便签就能接上。
- **档案**：工号、部门、城市、入职日期、历史工单。这些不常变，但每次办事都要用，而且必须准确、可追溯。

对应到代码里，就是本章的三层结构：

```text
                    ┌──────────────────────── 一次新请求 ────────────────────────┐
                    │                                                          │
  用户问题 ─────────▶│ ① 指代消解：把「那病假呢」补成「年假 病假」                 │
                    │        │                                                 │
                    │        ▼                                                 │
                    │ ② 召回：facts 逐条打分（关键词 70% + 时间衰减 30%）        │
                    │        │   过期 / 越权 / 被覆盖 → 直接淘汰                  │
                    │        ▼                                                 │
                    │ ③ 组装：画像 + 历史摘要 + 相关记忆 + 最近窗口 + 当前问题     │
                    │        │                                                 │
                    │        ▼                                                 │
                    │ ④ 调模型 → 回答 → 把本轮问答写回 window                    │
                    └──────────────────────────────────────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
  ┌───────────┐                 ┌─────────────┐                ┌──────────────┐
  │  window   │  满了就压缩      │   summary   │   长期沉淀      │ profile+facts │
  │ 最近 3 轮 │ ──────────────▶ │ 每轮一行要点 │ ─────────────▶ │ 画像与事实链  │
  │ 会话级    │                 │ 跨会话保留   │                │ 带来源/TTL    │
  └───────────┘                 └─────────────┘                └──────────────┘
        │                              │                              │
        └──────────── 都受「租户 + 员工 + 密级」三重约束 ─────────────┘
```

四类记忆的定位可以用一张表说清：

| 类型 | 存什么 | 活多久 | 写入时机 | 召回方式 |
| --- | --- | --- | --- | --- |
| 会话窗口 | 最近 N 轮原文 | 会话结束即清 | 每轮问答后 | 全量带上 |
| 滚动摘要 | 旧对话的一行要点 | 跨会话，限长 | 窗口溢出时 | 全量带上 |
| 员工画像 | 部门、城市、岗位 | 长期，随组织变动 | 入职/调动 | 每次都用 |
| 业务事实 | 余额、计划、材料 | 按 TTL，可过期 | 工具返回/员工自述 | 打分 Top-K |

**记忆（Memory）** 在这里的定义很朴素：让模型在「本次请求的输入」之外，还能用上之前的信息。它不是一个数据库名词，而是一组工程决策：写什么、写在哪、什么时候读、读出来给谁看。

### 2.1 为什么召回要打分

事实多了以后，不能每次都把所有事实塞进 Prompt。假设张伟有 40 条历史事实，全塞进去至少两三千 token，既贵又容易让模型抓错重点。所以要像搜索引擎一样先排序，取前几条。

本章的打分只有两项：

```text
score = 0.7 × 关键词重合率 + 0.3 × 0.5^(记忆年龄天数 / 14)
        └──── 相关性 ────┘   └──────── 新鲜度 ────────┘
```

- **关键词重合率**：问题被切成中文 2 字滑窗（「病假」「假材」……）和英文单词，事实文本同样切一遍，交集占问题的比例就是重合率。它粗糙，但完全可解释。
- **时间衰减**：半衰期 14 天。今天的事实新鲜度是 1.0，14 天前是 0.5，28 天前是 0.25。越久的事越可能已经变了。
- 权重 0.7 和 0.3 是拍的，但拍的也有依据：相关性决定「要不要用」，新鲜度只做微调；如果反过来，系统会优先推荐「刚发生的无关小事」。

用这个公式回看运行结果：病假材料是今天写的，重合率高、衰减满分，得分 0.378；年假余额是 11 天前写的，衰减只剩约 0.58，加上重合率不低，最终 0.252。它没有挤掉病假，但仍然稳稳留在前三——这正是我们要的效果：**新话题优先，旧上下文不断线**。

### 2.2 冲突：新事实不是覆盖旧事实

员工换部门、换工位、换手机号，是 HR 系统里天天发生的事。如果新事实直接覆盖旧事实，你会失去两样东西：一是「什么时候变的」，二是「谁说的、依据是什么」。出了纠纷，你没法证明当时系统里到底是什么。

本章的做法是「追加 + 失效标记」：同一个 `key` 下保留一条事实链，新值写入时把上一条的 `superseded_at` 标成今天，旧值不删除。召回时只取「未被覆盖且未过期」的那条。运行时你会看到工位从 `5F-08` 变成 `6F-12`，事实链是 `[('5F-08', 2026-11-16), ('6F-12', None)]`。

### 2.3 TTL 与隐私边界

**TTL（Time To Live，存活时间）** 的意思是：这条记忆最多活几天，超过就视为过期。出差计划这种一次性信息，记 14 天足够；病假材料这种制度类信息，可以记 180 天；年假余额变化快，记 30 天就要重新查。

比 TTL 更硬的是密级。本章把事实分成三级，和 `HR-PRIVACY-2025` 对齐：

- `L1` 公开：制度、流程。谁都能看。
- `L2` 内部：余额、绩效、候选人记录。按角色授权。
- `L3` 敏感：病历、身份证、银行卡。最小必要 + 审批 + 审计。

召回时同时检查「有没有过期」和「这个访问者有没有权限」。主管问「张伟病假原因」，系统可以告诉他「张伟在病假中，预计返岗时间」，但不该把「腰椎间盘突出」这五个字吐出来。代码里用 `audience` 参数模拟访问者身份，`LEVELS` 表决定谁能看哪一级。另外，任何展示给界面的文本都先过一遍 `mask_pii()`，手机号、邮箱、身份证号中间位打码。

> 💡 **小白提示**：不要被「记忆」这个词吓到。本章的实现就是一个字典加几个列表，没有向量库、没有数据库。先把「写什么、怎么读、什么时候删」想清楚，再谈存储引擎。

> ⚠️ **生产提醒**：记忆是隐私风险最高的模块之一。上线前至少确认三件事：每条记忆都带 `tenant_id` 与 `employee_id`；L3 数据加密存储且召回前鉴权；员工本人可以查看并申请删除自己的记忆。缺一条都别上线。

## 3. 动手：跑通 MemoryStore

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


在仓库根目录执行：

```powershell
python code/ch06_memory.py
```

完整代码如下（与 `code/ch06_memory.py` 一致）：

```python
"""第 06 章：Memory —— 让助手记住员工，但别记到越界。

三层：window 最近 N 轮原文、summary 旧对话要点、profile + facts 长期画像与事实；
召回 = 关键词 70% + 时间衰减 30%，不依赖向量库。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import employee
from common.text import estimate_tokens, mask_pii

TODAY = date(2026, 11, 16)  # 固定「今天」，保证每次运行结果一致
STOP = {"什么", "怎么", "可以", "我们", "你们", "一下", "这个", "那个", "现在", "还有", "的话"}

def keywords(text: str) -> set[str]:
    text = text.lower()
    words = {w for w in re.findall(r"[a-z0-9]+", text) if w not in STOP}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words |= {run[i : i + 2] for i in range(len(run) - 1)}
    return {w for w in words if w not in STOP}

@dataclass
class Fact:
    key: str
    value: str
    source: str
    created_at: date
    confidence: float = 0.8
    ttl_days: int | None = None
    sensitivity: str = "L1"  # L1 公开 / L2 内部 / L3 敏感
    superseded_at: date | None = None

    def age_days(self, now: date) -> int:
        return (now - self.created_at).days

    def expired(self, now: date) -> bool:
        return self.ttl_days is not None and self.age_days(now) > self.ttl_days

    def text(self) -> str:
        return f"{self.key}：{mask_pii(self.value)}"

class MemoryStore:
    WINDOW_TURNS = 6  # 只保留最近 3 轮问答
    HALF_LIFE = 14.0  # 时间衰减半衰期：14 天前的记忆权重减半
    LEVELS = {"L1": {"self", "hr", "manager", "hr_admin"}, "L2": {"self", "hr", "hr_admin"}, "L3": {"self", "hr_admin"}}

    def __init__(self, employee_id: str, today: date = TODAY) -> None:
        self.employee_id = employee_id
        self.today = today
        record = employee(employee_id) or {}
        self.profile = {"name": record.get("name", "未知"), "department": record.get("department", ""),
                        "city": record.get("city", ""), "position": record.get("position", "")}
        self.profile_history: dict[str, list[tuple[date, str]]] = {}
        self.facts: dict[str, list[Fact]] = {}
        self.window: list[dict] = []
        self.summary_lines: list[str] = []
        self.audit: list[str] = []

    def add_turn(self, role: str, content: str) -> None:
        self.window.append({"role": role, "content": content})
        if len(self.window) > self.WINDOW_TURNS:
            drop = len(self.window) - self.WINDOW_TURNS
            drop += drop % 2  # 成对丢弃，别把一问一答拆散
            self._compress(self.window[:drop])
            self.window = self.window[drop:]

    def _compress(self, turns: list[dict]) -> None:
        for i in range(0, len(turns) - 1, 2):
            ask = turns[i]["content"] if turns[i]["role"] == "user" else turns[i + 1]["content"]
            answer = turns[i + 1]["content"] if turns[i]["role"] == "user" else turns[i]["content"]
            numbers = re.findall(r"\d+(?:\.\d+)?", ask + answer)
            line = f"{self.today:%m-%d} 问{ask[:24]}；答{answer[:28]}"
            if numbers:
                line += f"（数字：{'/'.join(dict.fromkeys(numbers))[:20]}）"
            self.summary_lines.append(line)
        self.summary_lines = self.summary_lines[-6:]  # 摘要也不能无限长

    def observe(self, key: str, value: str, source: str, *, created_at: date | None = None, **kwargs: object) -> str:
        new = Fact(key=key, value=value, source=source, created_at=created_at or self.today, **kwargs)  # type: ignore[arg-type]
        history = self.facts.setdefault(key, [])
        if history and history[-1].value != value and history[-1].superseded_at is None:
            history[-1].superseded_at = self.today
            self.audit.append(f"冲突：{key} 由「{history[-1].value}」改为「{value}」，来源 {source}")
            outcome = "conflict"
        else:
            outcome = "new"
        history.append(new)
        return outcome

    def update_profile(self, key: str, value: str, source: str) -> bool:
        old = self.profile.get(key)
        if old == value:
            return False
        self.profile[key] = value
        self.profile_history.setdefault(key, []).append((self.today, value))
        self.audit.append(f"画像：{key} {old} → {value}（{source}）")
        return True

    def recall(self, question: str, audience: str = "self", top_k: int = 3) -> list[dict]:
        """关键词 70% + 时间衰减 30%；过期、越权、被覆盖的事实不参与。"""
        query = keywords(self._resolve(question))
        scored: list[dict] = []
        for fact in (f for group in self.facts.values() for f in group):
            if fact.superseded_at is not None or fact.expired(self.today):
                continue
            if audience not in self.LEVELS[fact.sensitivity]:
                self.audit.append(f"拒绝召回：{fact.key} 为 {fact.sensitivity}")
                continue
            hit = query & keywords(fact.text())
            if not hit:
                continue
            overlap = len(hit) / max(len(query), 1)
            decay = 0.5 ** (fact.age_days(self.today) / self.HALF_LIFE)
            scored.append({"text": fact.text(), "score": round(0.7 * overlap + 0.3 * decay, 3),
                           "age_days": fact.age_days(self.today), "source": fact.source})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _resolve(self, question: str) -> str:
        if not any(word in question for word in ("那", "它", "这个", "还有")) or not self.summary_lines:
            return question
        topic = self.summary_lines[-1].split("问", 1)[-1].split("；")[0]
        return f"{topic} {question}"

    def memory_block(self, question: str, audience: str = "self") -> str:
        hits = self.recall(question, audience)
        who = f"员工：{self.profile['name']}（{self.employee_id}，{self.profile['department']}，{self.profile['city']}）"
        found = "；".join(f"[{h['score']}] {h['text']}" for h in hits) or "（无）"
        return f"{who}\n历史摘要：{'；'.join(self.summary_lines) or '（无）'}\n相关记忆：{found}"

    def prompt_messages(self, question: str, audience: str = "self") -> list[dict]:
        head = "你是 HR 共享服务中心的助手。只使用下方记忆回答，不确定就说不确定。\n"
        return [{"role": "system", "content": head + self.memory_block(question, audience)},
                *self.window, {"role": "user", "content": question}]

def main() -> None:
    print("=== 1. 上周（11-05）：张伟在会话 A 里连续问年假 ===")
    memory = MemoryStore("E1001", today=date(2026, 11, 5))
    memory.observe("年假余额", "15 天额度，已休 2 天，剩 13 天", "HR 系统 leave_balance", ttl_days=30)
    memory.observe("年假申请", "计划 12 月休 3 天，需提前 3 个工作日提交", "员工自述", ttl_days=60)
    memory.add_turn("user", "我年假还剩几天？")
    memory.add_turn("assistant", "你今年年假 15 天，已休 2 天，还剩 13 天，最小请假单位 0.5 天。")
    memory.add_turn("user", "我想 12 月休 3 天，额度够吗？")
    memory.add_turn("assistant", "够，还剩 13 天，扣掉 3 天还有 10 天。")
    memory.add_turn("user", "需要提前几天申请？")
    memory.add_turn("assistant", "至少提前 3 个工作日，连续休 3 天由直属主管审批。")
    memory.add_turn("user", "没休完能跨年吗？")
    memory.add_turn("assistant", "最多结转 5 天到次年 3 月 31 日，逾期作废。")
    print(f"窗口轮次：{len(memory.window)}｜摘要行数：{len(memory.summary_lines)}｜摘要：{memory.summary_lines}")

    print("\n=== 2. 今天（11-16）：新会话，窗口清空，摘要与事实跨会话保留 ===")
    memory.today = TODAY
    memory.window.clear()  # 短期窗口是会话级的，新会话就该清空
    memory.observe("病假材料", "需二级及以上医院证明，当天 10:00 前报备，返岗 2 个工作日内补交", "HR-LEAVE-2025", ttl_days=180)
    question = "那病假呢？"
    print("原问题：", question, "→ 消解后：", memory._resolve(question))
    print("记忆块：\n" + memory.memory_block(question))
    hits = memory.recall(question)
    print("召回明细（关键词 70% + 时间衰减 30%）：")
    for hit in hits:
        print(f"  {hit['score']:.3f}  {hit['age_days']:>3} 天前  {hit['text'][:46]}  ← {hit['source']}")

    print("\n=== 3. 冲突：张伟从技术部转到产品部，工位也换了 ===")
    changed = memory.update_profile("department", "产品部", "组织架构调整 2026-11-16")
    print("画像更新：", changed, "｜当前部门：", memory.profile["department"], "｜历史：", memory.profile_history)
    memory.observe("工位", "5F-08", "行政系统", ttl_days=90)
    memory.observe("工位", "6F-12", "行政系统", ttl_days=90)
    print("工位事实链：", [(f.value, f.superseded_at) for f in memory.facts["工位"]])
    print("审计：", *memory.audit, sep="\n  ")

    print("\n=== 4. TTL 与隐私：过期的不召回，L3 的不该被主管看见 ===")
    memory.observe("出差计划", "2026-09 深圳出差 3 天", "员工自述", created_at=date(2026, 9, 1), ttl_days=14)
    memory.observe("病假原因", "腰椎间盘突出，医嘱休息 5 天", "员工自述", ttl_days=30, sensitivity="L3")
    expired_hits = memory.recall("出差", audience="manager")
    manager_hits = memory.recall("病假原因", audience="manager")
    expired = memory.facts["出差计划"][0].expired(memory.today)
    print("出差计划是否过期：", expired, "｜主管召回「出差」：", [h["text"] for h in expired_hits] or "（空：已过期）")
    print("主管召回「病假原因」：", [h["text"] for h in manager_hits] or "（空）")
    print("本人召回「病假原因」：", [h["text"] for h in memory.recall("病假原因", audience="self")])

    messages = memory.prompt_messages("我想请两天病假，需要什么材料？")
    print(f"\n=== 5. 拼进 Prompt：messages={len(messages)} 条，估算 {estimate_tokens(str(messages))} token ===")
    print(messages[0]["content"])

    assert memory.profile["department"] == "产品部" and len(memory.profile_history["department"]) == 1
    assert any(h["text"].startswith("年假") for h in hits), "跨会话后应召回上周的年假事实"
    assert not any(h["text"].startswith("出差计划") for h in expired_hits)
    assert not any(h["text"].startswith("病假原因") for h in manager_hits)
    print("\n全部断言通过：记忆能跨会话召回、冲突可追溯、TTL 与 L3 权限生效。")

if __name__ == "__main__":
    main()
```

运行后你会看到（节选）：

```text
=== 1. 上周（11-05）：张伟在会话 A 里连续问年假 ===
窗口轮次：6｜摘要行数：1｜摘要：['11-05 问我年假还剩几天？；答你今年年假 15 天，已休 2 天，还剩 13 天，最小（数字：15/2/13/0.5）']

=== 2. 今天（11-16）：新会话，窗口清空，摘要与事实跨会话保留 ===
原问题： 那病假呢？ → 消解后： 我年假还剩几天？ 那病假呢？
记忆块：
员工：张伟（E1001，技术部，上海）
历史摘要：11-05 问我年假还剩几天？；答你今年年假 15 天，已休 2 天，还剩 13 天，最小（数字：15/2/13/0.5）
相关记忆：[0.378] 病假材料：需二级及以上医院证明，当天 10:00 前报备，返岗 2 个工作日内补交；[0.252] 年假余额：15 天额度，已休 2 天，剩 13 天；[0.252] 年假申请：计划 12 月休 3 天，需提前 3 个工作日提交
召回明细（关键词 70% + 时间衰减 30%）：
  0.378    0 天前  病假材料：需二级及以上医院证明，当天 10:00 前报备，返岗 2 个工作日内补交  ← HR-LEAVE-2025
  0.252   11 天前  年假余额：15 天额度，已休 2 天，剩 13 天  ← HR 系统 leave_balance
  0.252   11 天前  年假申请：计划 12 月休 3 天，需提前 3 个工作日提交  ← 员工自述
```

注意几个细节：

- 会话 A 里说了 8 句（4 轮），窗口只留最近 6 句，最早的一问一答被压成了一行摘要。
- 新会话清空了窗口，但摘要和事实还在，所以「那病假呢」既召回了上周的年假，也召回了今天的病假材料。
- 两条年假事实的分数都是 0.252，不是巧合：它们同一天写入，时间衰减相同，关键词重合率也接近。
- 第 4 节里，主管看不到 L3 的病假原因，但本人可以；过期的出差计划对谁都不出现。

> 🧪 **动手**：先运行一遍，把 `memory.recall(question)` 的 `top_k` 改成 1，再跑一次。你会看到「年假申请」被挤掉，但「年假余额」仍在——说明排序是按分数，不是按写入顺序。

## 4. 逐行拆解

### 4.1 为什么「成对丢弃」

`add_turn` 里有一行不起眼但重要的代码：

```python
drop = len(self.window) - self.WINDOW_TURNS
drop += drop % 2  # 成对丢弃，别把一问一答拆散
```

如果窗口上限是 6 条、现在有 7 条，直接丢掉最旧 1 条，就会留下一个「没有问题的回答」。摘要压缩是按对处理的，`_compress` 的循环步长是 2；一旦序列错位，后面所有问答都会错配。所以这里宁可多丢一条，也要保证成对。

这也是所有记忆系统的通病：**窗口按「条」管理，语义却按「轮」组织**。生产代码里通常直接把窗口定义成 `list[Turn]`，一个 `Turn` 包含 `user` 和 `assistant` 两条消息，从结构上避免错位。

### 4.2 摘要为什么必须保留数字

`_compress` 把一问一答压成一行，看起来损失很大，但它专门做了一件事：

```python
numbers = re.findall(r"\d+(?:\.\d+)?", ask + answer)
if numbers:
    line += f"（数字：{'/'.join(dict.fromkeys(numbers))[:20]}）"
```

因为 HR 对话里最有复用价值的就是数字：余额 13 天、结转 5 天、提前 3 个工作日、最小单位 0.5 天。如果摘要只写「张伟问过年假，助手已答复」，下次他问「那我还能休几天」，模型仍然答不出来。保留数字，摘要才真的能接住后续追问。

当然，数字也会过期。所以摘要只是「线索」，真正的答案仍然以 `facts` 里带 TTL 的事实为准；摘要负责让对话连贯，事实负责让答案准确。

### 4.3 打分公式的两个极端

`score = 0.7 × overlap + 0.3 × decay`，两项都有明确的失败模式：

- 只有 overlap：上周刚聊过的年假和三个月前的旧年假余额分数一样高，系统可能把过期信息顶上来。
- 只有 decay：今天刚记的「食堂菜单」会压过 11 天前真正相关的年假记录。

0.7 比 0.3 的意思是「相关性优先，新鲜度修正」。你会看到病假材料 0.378 排第一，年假余额 0.252 排第二：前者既相关又新鲜，后者相关但旧了一些。这个排序符合人的直觉。

还有一个隐藏细节：分母是 `max(len(query), 1)`。如果问题被停用词过滤成空集合（比如用户只发了一个「？」），所有事实的重合率都是 0，此时排序完全由时间衰减决定。这比抛异常友好，但也提醒你：**召回为空时要显式处理，不要硬编**。

### 4.4 冲突更新：保留证据链

`observe` 的逻辑只有三行是关键：

```python
if history and history[-1].value != value and history[-1].superseded_at is None:
    history[-1].superseded_at = self.today
    self.audit.append(f"冲突：{key} 由「{history[-1].value}」改为「{value}」，来源 {source}")
```

新值不覆盖旧值，而是把旧值标记为「已失效」，再追加新值。这样做有三个好处：

1. 召回时只看最新有效值，不会把两个部门同时塞给模型。
2. 审计日志里有完整的变更轨迹，出了纠纷能回溯。
3. 未来如果要做「时间旅行」查询（比如查 10 月的部门），历史数据还在。

代价是存储会增长。生产上通常给历史记录加保留期，比如只保留 2 年，或者把变更事件写进独立的审计表，主表只留当前值。

### 4.5 指代消解为什么不用模型

`_resolve` 只做了一件很土的事：如果问题里有「那 / 它 / 这个 / 还有」，就从摘要最后一行里取出上一个话题，拼到问题前面。

```python
topic = self.summary_lines[-1].split("问", 1)[-1].split("；")[0]
return f"{topic} {question}"
```

为什么不用模型来做指代消解？因为在记忆模块里，模型调用会带来三个新问题：延迟、成本、不确定性。而「那病假呢」这种指代，规则能覆盖 80% 的高频场景；剩下 20% 交给模型兜底也来得及。工程上的顺序应该是：**先用确定性的规则兜住大多数，再用模型处理长尾**，而不是反过来。

当然，这个实现很脆：它假设摘要格式固定、最后一行一定是上一轮问题。生产上更稳的做法是把「当前话题」作为一个独立字段维护，而不是从文本里拆。

### 4.6 TTL 与权限是两道独立的闸门

召回循环里有两个 `continue`：

```python
if fact.superseded_at is not None or fact.expired(self.today):
    continue
if audience not in self.LEVELS[fact.sensitivity]:
    continue
```

它们解决的是不同问题。过期解决「信息还准不准」，权限解决「这个人该不该看」。有人会把两者混在一起，用「过期就删」代替权限控制，这是危险的：一条没过期的病历，仍然不该给主管看。

第 3 节运行结果的第 4 段就是证明：主管问「病假原因」，只召回 L1 的病假材料；本人问同样的问题，能看到 L3 的病假原因。同一个问题、同一个存储，答案不同，差别只在 `audience`。

## 5. 实验：改几个参数，看记忆怎么变形

### 实验一：把窗口从 6 改成 2

把 `WINDOW_TURNS = 6` 改成 `2`，重跑。你会看到摘要行数从 1 变成 3，窗口里只剩最后一轮。含义是：更激进的压缩会让摘要承担更多上下文，摘要质量差的话，指代消解会更容易失败。生产上这个值要按「一轮对话平均多少 token」和「模型窗口多大」一起算。

### 实验二：把半衰期从 14 天改成 1 天

把 `HALF_LIFE = 14.0` 改成 `1.0`，重跑。11 天前的年假余额，衰减项会变成 `0.5^11 ≈ 0.0005`，几乎只剩关键词项，分数会掉到 0.2 附近；如果关键词重合率再低一点，它会被今天的病假材料彻底挤掉。这解释了为什么「短半衰期适合高频变化的业务，长半衰期适合稳定偏好」。

### 实验三：把病假原因的 TTL 改成 0

把 `observe("病假原因", ..., ttl_days=30, sensitivity="L3")` 的 `ttl_days` 改成 `0`，重跑。你会发现写入当天它**仍然能被召回**，因为 `expired` 用的是严格大于：`age_days=0 > 0` 为假。次日它才过期。这个细节值得停下来想一秒：**边界条件必须用测试固定住**，否则「当天过期」和「次日过期」会差出一整天的合规风险。如果业务要求「写入即过期」，把比较改成 `>=`，或者干脆不写入。

### 实验四：切换访问者

把第 5 节的 `memory.prompt_messages("我想请两天病假，需要什么材料？")` 改成 `memory.prompt_messages("我想请两天病假，需要什么材料？", audience="manager")`，重跑。此时病假原因已经在第 4 节写入，所以你会看到它从「相关记忆」里消失，只剩病假材料。再把 `audience` 改成 `"hr_admin"`，L3 又回来了。这说明权限判断发生在召回阶段，而不是展示阶段——越早拦截，泄露面越小。

## 6. 工程化视角

本章的 `MemoryStore` 是内存版，进程一退就没了。要上生产，至少补四块：

**持久化。** 最小方案是 SQLite 三张表：`profile`（员工画像 + 版本）、`facts`（key、value、source、created_at、ttl、sensitivity、superseded_at）、`turns`（会话 id、角色、内容、时间）。查询「当前有效事实」就是 `WHERE superseded_at IS NULL AND (ttl IS NULL OR created_at + ttl > now)`。

**多租户与隔离。** 所有表都要有 `tenant_id`，所有查询都必须带上它。缓存键也要带，例如 `mem:{tenant}:{employee}:facts`。共享服务中心最容易出的事故，就是把 A 公司的员工记忆召回给 B 公司的客服。

**加密与审计。** L3 字段单独加密（应用层加密或数据库透明加密），读取时二次鉴权并写审计日志。审计日志本身要防篡改，第 12 章会讲哈希链。

**召回升级。** 关键词召回在事实少的时候够用，事实到几千条就会遇到同义词问题（「年休」和「年假」）。下一步通常是混合召回：关键词保底，向量召回补语义，再用 RRF 融合。这也是第 09 章的主题。

还有一个经常被忽略的点：**记忆要能被员工看见和删除**。隐私规范里写了最小必要和保留期限，产品上就要有「我的记忆」页面，允许查看、纠正、删除。否则你没法回答「你们到底记了我什么」。

## 7. 常见坑

**坑 1：把整段对话无限追加进 Prompt。**
现象：聊到第 20 轮，请求突然报超长，或者费用翻倍。
原因：只做了「写」，没做「压缩与淘汰」。
解法：窗口按轮数或 token 双重上限；溢出部分必须进摘要，且摘要自身也要限长。

**坑 2：摘要只留结论，不留数字和出处。**
现象：摘要说「张伟咨询过年假」，下次问「还剩几天」还是答不出。
原因：压缩时把可复用的事实当成了废话。
解法：摘要模板固定保留「时间、主题、关键数字、结论」，并为重要事实单独建 `Fact`。

**坑 3：新事实直接覆盖旧事实。**
现象：员工问「我什么时候换的部门」，系统答不出来；审计也查不到。
原因：`UPDATE` 而不是追加 + 失效标记。
解法：保留事实链，主表只留当前值，历史进审计表。

**坑 4：把病历、薪资当成普通事实长期记住。**
现象：主管一句「张伟最近怎么样」，助手把病假原因和薪资带宽一起召回。
原因：没有密级字段，召回不鉴权。
解法：写入时强制标 `sensitivity`，L3 默认不进普通召回；展示前统一 `mask_pii`。

**坑 5：用 `datetime.now()` 做时间判断。**
现象：测试今天过、明天挂；跨时区部署后 TTL 全乱。
原因：时间源不固定、时区不统一。
解法：注入 `today` 参数（本章做法），生产统一用 UTC 存储、展示时转本地时区。

> ⚠️ **生产提醒**：不要用「员工说过的所有话」当记忆语料。员工在咨询里可能提到病情、家庭变故、求职意向，这些都不该被默认长期保存。写入前问一句：这条信息如果明天被本人看到，他会不会介意？会，就别存。

## 8. 练习

### 练习 1（易）：让时间衰减更激进

把 `HALF_LIFE` 改成 `3.0`，重跑，记录年假余额和年假申请的分数变化，并解释为什么两条事实的分数仍然相同。

<details><summary>参考答案</summary>

```python
HALF_LIFE = 3.0
```

11 天前的事实，衰减项从 `0.5^(11/14) ≈ 0.58` 变成 `0.5^(11/3) ≈ 0.078`，总分从约 0.252 降到约 0.16（关键词项不变）。两条事实同一天写入、关键词重合率接近，所以分数依然相同。这说明**时间衰减只能区分「新旧」，不能区分「相关」**；要区分相关，得靠更好的召回（关键词权重、向量、rerank）。

</details>

### 练习 2（中）：给事实加生效区间

现在的 `Fact` 只有 `created_at` 和 `ttl_days`。请增加 `valid_from` / `valid_to` 两个字段，让「2024 版制度」这类历史事实只在查询历史时可见。

<details><summary>参考答案</summary>

在 `Fact` 中加字段，默认 `valid_from=created_at`、`valid_to=None`：

```python
valid_from: date | None = None
valid_to: date | None = None

def in_range(self, now: date) -> bool:
    start = self.valid_from or self.created_at
    return start <= now and (self.valid_to is None or now <= self.valid_to)
```

`recall` 里把 `fact.expired(...)` 换成 `not fact.in_range(self.today)`。注意 `valid_to` 是闭区间还是开区间要写清楚，制度类数据通常用「失效日次日零点」作为 `valid_to`，避免当天算错。

</details>

### 练习 3（中）：摘要只保留未完成任务

修改 `_compress`，让摘要只保留「还没办完的事」，例如「张伟 12 月计划休 3 天，尚未提交申请」。

<details><summary>参考答案</summary>

最简单的做法是给摘要行加一个状态判断：如果问题和回答里出现「计划」「打算」「还没」「待」等词，就标成 `TODO`，否则只保留一句极短的记录或直接丢弃。

```python
TODO_WORDS = ("计划", "打算", "还没", "待", "下周", "明天")
if any(word in ask for word in TODO_WORDS):
    self.summary_lines.append(f"TODO {line}")
```

更工程化的做法是单独维护 `tasks: list[dict]`，字段为 `what / due / status`，摘要只引用任务 id。这样「未完成任务」可以跨会话查询、可以标记完成，而不是埋在自然语言里。

</details>

### 练习 4（难）：模拟员工换部门后的冲突合并

张伟从技术部转到产品部，同时工位从 `5F-08` 变成 `6F-12`。请让画像、工位事实、摘要三处都更新，并保证召回时不会同时返回旧部门。

<details><summary>参考答案</summary>

关键点有三个：

1. 画像更新走 `update_profile`，保留历史；
2. 工位走 `observe`，旧值标 `superseded_at`；
3. 摘要里补一行变更记录，否则下次对话模型不知道「他换部门了」。

```python
memory.update_profile("department", "产品部", "组织架构调整")
memory.observe("工位", "6F-12", "行政系统", ttl_days=90)
memory.summary_lines.append(f"{memory.today:%m-%d} 组织调整：技术部 → 产品部，工位 6F-12")
```

验证方式：`recall("工位")` 只返回 `6F-12`；`memory.facts["工位"][0].superseded_at` 不为 `None`；把 `audience` 换成 `manager` 也看不到任何人事调整细节之外的隐私字段。

</details>

### 练习 5（难）：给记忆加「遗忘」接口

实现 `forget(key: str, reason: str)`，要求：立即从召回中消失、保留审计记录、支持按员工整体清除。

<details><summary>参考答案</summary>

不要物理删除，除非合规要求。推荐「软删除 + 审计」：

```python
def forget(self, key: str, reason: str) -> int:
    count = 0
    for fact in self.facts.get(key, []):
        if fact.superseded_at is None:
            fact.superseded_at = self.today
            count += 1
    self.audit.append(f"遗忘：{key}（{reason}），影响 {count} 条")
    return count
```

整体清除则遍历 `self.facts`，对每条有效事实打标记，并清空 `summary_lines` 与 `window`。注意：审计日志本身不能删，要保留「谁在什么时候要求删除」的记录；如果法务要求不可恢复，还要在存储层做真正的擦除。

</details>

## 9. 小结与下一章

三句话记住本章：

1. 记忆不是「存得越多越好」，而是**分层**：窗口管连贯、摘要管跨会话、画像和事实管准确。
2. 召回要**打分**：相关性优先、新鲜度修正，过期和越权必须在召回阶段就拦掉。
3. 冲突要**留痕**：新值生效、旧值失效、审计可查，这比「覆盖」多花一点存储，但省下的是纠纷成本。

下一章我们会遇到一个新问题：记忆、制度、历史、工具描述全都塞进上下文，一次请求很快就超过预算。怎么分配、怎么裁剪、怎么压缩，就是第 07 章要讲的 Context Engineering。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **MessagesState + InMemorySaver + trim_messages**，完整代码见 `code/ch06_memory.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain_core.messages import trim_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import MessagesState, StateGraph

graph = StateGraph(MessagesState)
graph.add_node("assistant", assistant_node)
graph.set_entry_point("assistant")
app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "employee-E1001"}}

history = trim_messages(state["messages"], max_tokens=80,
                        token_counter=count_tokens, strategy="last")
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 会话 | `MessagesState` |
| 线程 | `InMemorySaver` + `thread_id` |
| 裁剪 | `trim_messages` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch06_memory.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
