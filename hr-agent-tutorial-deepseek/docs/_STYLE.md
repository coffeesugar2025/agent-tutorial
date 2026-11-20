# 教程写作规范（内部使用）

本文件是写作与代码的统一约定。所有章节必须遵守，保证 18 章读起来像一本书，而不是 18 篇拼凑的博客。

## 1. 读者与语气

- 读者画像：会一点 Python 语法、没做过 AI 应用、想转行或刚入行的开发者；也可能是产品/测试转 Agent 工程。
- 默认读者**不知道**什么是 token、embedding、function calling。每个术语第一次出现必须用一句大白话解释，再给英文名。
- 用“你”称呼读者，用“我们”一起做实验。语气像一位耐心的同事，不端着，也不卖焦虑。
- 先讲“为什么需要”，再讲“是什么”，最后讲“怎么写”。不要一上来甩定义。
- 所有 HR 场景必须是**具体的人 + 具体的事 + 具体的约束**，不要写“某企业希望提升效率”这种空话。
- 不写“随着大模型时代的到来”“赋能”“闭环”这类营销词。能用数字就用数字。

## 2. 章节结构（必须遵守）

每章 Markdown 以 YAML frontmatter 开头：

```yaml
---
title: "02 | Agent Loop：让模型学会「再来一轮」"
slug: "agent-loop"
order: 2
part: "单 Agent 核心"
minutes: 50
difficulty: "入门"
prerequisites: ["01"]
summary: "一句话说明本章产出，不超过 50 字。"
---
```

正文固定九段，标题可以微调，但顺序不变：

1. `## 0. 本章你会得到什么`：3–5 条可验证的学习目标。
2. `## 1. 场景`：一个 HR 真实痛点故事，带人物、数字、失败后果。
3. `## 2. 概念`：核心原理，至少一张 ASCII 图；先类比后定义。
4. `## 3. 动手`：完整可运行代码，逐段解释。代码块必须与 `code/chXX_*.py` 一致或明显是其简化版。
5. `## 4. 逐行拆解`：挑 3–6 个关键点讲透，不要逐字翻译代码。
6. `## 5. 实验`：让读者改 2–3 个参数并观察结果，给出预期现象。
7. `## 6. 工程化视角`：这段最小实现上生产还缺什么，连接到后续章节。
8. `## 7. 常见坑`：3–6 条，每条“现象 → 原因 → 解法”。
9. `## 8. 练习`：3–5 题，由易到难；参考答案放在 `<details>` 中。
10. `## 9. 小结与下一章`：3 条要点 + 一句过渡。

每章正文 3000–5500 个汉字（不含代码），预计阅读 30–60 分钟。宁可把一个点讲透，不要罗列十个名词。

## 3. 排版约定

- 提示块用引用 + 固定前缀，前端会统一着色：
  - `> 💡 **小白提示**：...`
  - `> ⚠️ **生产提醒**：...`
  - `> 🧪 **动手**：...`
  - `> 📌 **考点**：...`（求职相关）
- 图一律用 ```text 代码块画 ASCII 图，保证 GitHub、终端、网页都能看。
- 表格用于对比，不超过 5 列。
- 代码块必须标注语言：python、bash、json、text、sql、cypher。
- 命令行统一用 PowerShell（Windows 读者）与 bash 二选一，默认 PowerShell，必要时注明 macOS/Linux 的差异。
- 文件名、函数名、字段名用反引号。
- 不要用相对链接指向仓库文件（网页会 404），直接写 `code/ch02_agent_loop.py` 这样的路径文本。
- 允许 `<details><summary>参考答案</summary>...</details>`，除此之外不要写 HTML。
- 中文与英文/数字之间加空格：`Python 3.12`、`3 天年假`、`Top-K`。
- 中文标点用全角，代码内用半角。

## 4. 代码规范

- Python 3.12，类型标注，`from __future__ import annotations`。
- **所有 demo 必须基于 LangChain 1.x / LangGraph 1.x**：模型用 `BaseChatModel`，工具用 `@tool`，单 Agent 用 `create_agent`，流程/循环/多 Agent 用 `StateGraph`，HITL 用 `interrupt`/`Command` 或 `HumanInTheLoopMiddleware`，RAG 用 `RecursiveCharacterTextSplitter` / `InMemoryVectorStore` / `BM25Retriever`。
- 离线演示统一使用 `common.lc.MockChatModel`（LangChain 原生 ChatModel），真实模型使用 `common.lc.get_chat_model()`（`ChatOpenAI` 兼容 DeepSeek/Qwen/Ollama/vLLM）。
- 允许保留少量自定义逻辑（权限、幂等、审计、评分、状态机守卫），但**核心编排必须走 LangChain/LangGraph**，不能再用自制的 dict 消息循环作为主实现。
- 不调用网络、不需要 API Key。结尾说明如何切真实模型。
- 代码要能解释“框架帮你做了什么”，而不是只贴 API。每章至少指出一个 LangChain 抽象（Runnable、Tool、StateGraph、Retriever、Checkpointer）解决了什么问题。
- 每个脚本必须能从仓库任意目录运行：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.llm import MockLLM, assistant, system, tool_message, user
```

- 统一入口：

```python
def main() -> None:
    print("=== 1. 场景 ===")
    ...

if __name__ == "__main__":
    main()
```

- 每个脚本控制在 80–220 行，中文注释解释“为什么”，不要注释“这行给变量赋值”。
- 关键步骤打印出来，让读者不看代码也能看懂运行过程。用 `===` 分节。
- 结尾做 2–4 个 `assert`，把本章的核心结论变成可执行断言；运行失败就说明没学懂。
- 不写 `input()`、不写 `time.sleep()` 超过 0.5 秒、不写死循环。所有循环必须有最大步数。
- Mock 数据统一从 `common.data` 读取，不要自己另造员工/制度。需要新数据时放在 `code/data/` 下并在文档说明。
- 数据全部虚构；不要出现真实公司名、真实手机号、真实身份证号。
- 不在代码里打印 API Key；真实模型示例只写环境变量名。

## 5. 内容质量红线

- 不把 MockLLM 说成“真实大模型”。必须明确：离线跑的是确定性脚本，接真实模型只需换环境变量。
- 不承诺“学完就能年薪百万”。求职章节讲清楚能力映射、作品集和面试准备即可。
- 不给医疗、法律、解雇等高风险场景下“AI 可以直接做决定”的暗示；必须有人工审批与拒答边界。
- 引用制度必须带文档编号、版本、条款位置；没有证据就拒答，这是全书反复训练的习惯。
- 涉及候选人/员工个人信息时，必须出现脱敏、最小权限、审计中的至少一项。
- 评测章节必须包含失败案例，不能只报喜。

## 6. 每章自检清单

- [ ] frontmatter 完整，slug 与文件名约定一致，order 正确。
- [ ] 九段结构齐全，有场景故事、ASCII 图、可运行代码、练习与答案。
- [ ] 代码基于 LangChain 1.x / LangGraph，至少使用 `create_agent`、`@tool`、`StateGraph`、`ChatPromptTemplate` 中的两项；没有自制的消息循环作为主实现。
- [ ] 章节开头有“框架说明”提示块，指出本章用到的 LangChain/LangGraph API。
- [ ] 代码已实际运行通过，输出与文中一致。
- [ ] 术语第一次出现有解释。
- [ ] 至少 2 处“生产提醒”，且不是废话。
- [ ] 没有真实 PII，没有密钥，没有网络依赖。
- [ ] 结尾给出下一章的自然过渡。
