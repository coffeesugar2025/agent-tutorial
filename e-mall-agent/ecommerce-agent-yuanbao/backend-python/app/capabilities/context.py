"""Context Engineering：Token 预算 / 上下文压缩 / 裁剪 / 优先级。

把「上下文」当成有价格的稀缺资源来分配，而不是无脑拼接历史。

  estimate_tokens   中英混排近似估算（中文按字，英文按 4 字符，标点折半）
  TokenBudget       为 system / tools / history / retrieved / output 预留额度
  compress         抽取式压缩：保系统提示、保最近 N 轮、旧轮摘要、工具结果截断
  select_context   按优先级裁剪到预算内，并报告被丢弃的内容
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff]")


def estimate_tokens(text: str) -> int:
    """近似估算：中文 1 字≈1 token；非中文 4 字符≈1 token；空白折半。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    rest = len(text) - cjk
    return max(1, cjk + int(rest / 4) + int(len(text.split()) / 8))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(str(m.get("content", ""))) + 4 for m in messages)


@dataclass
class TokenBudget:
    total: int = 4096
    reserve_system: int = 600
    reserve_tools: int = 500
    reserve_output: int = 512
    reserve_retrieved: int = 900

    @property
    def available_for_history(self) -> int:
        return max(0, self.total - self.reserve_system - self.reserve_tools
                   - self.reserve_output - self.reserve_retrieved)

    def report(self) -> dict[str, int]:
        return {"total": self.total, "system": self.reserve_system,
                "tools": self.reserve_tools, "output": self.reserve_output,
                "retrieved": self.reserve_retrieved,
                "history": self.available_for_history}


@dataclass
class CompressionResult:
    messages: list[dict[str, Any]]
    original_tokens: int
    compressed_tokens: int
    dropped_turns: int
    summarized_turns: int
    truncated_tool_results: int
    strategy: str = "system+recent+extractive-summary"
    summary: str = ""

    @property
    def saved_ratio(self) -> float:
        return round(1 - self.compressed_tokens / max(1, self.original_tokens), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages, "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "saved_ratio": self.saved_ratio, "dropped_turns": self.dropped_turns,
            "summarized_turns": self.summarized_turns,
            "truncated_tool_results": self.truncated_tool_results,
            "strategy": self.strategy, "summary": self.summary,
        }


def _extractive_summary(text: str, max_chars: int = 120) -> str:
    """抽取式摘要：保数字、金额、SKU、状态词，去掉客套话。"""
    keep = re.findall(r"(?:¥\s?\d+(?:\.\d+)?|SKU-\d+|EC\d+|订单号?\s*\S+|"
                      r"\d+(?:\.\d+)?\s*(?:元|件|天)|运输中|已签收|待付款|有货|缺货|"
                      r"符合|不符合|到手价?)", text)
    head = text.strip().replace("\n", " ")[:max_chars]
    uniq = []
    for k in keep:
        if k not in uniq:
            uniq.append(k)
    tail = "、".join(uniq[:8])
    return (head + ("｜关键事实：" + tail if tail else ""))[: max_chars + 80]


def truncate_tool_result(text: str, max_chars: int = 300) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "…（已截断，完整数据在卡片/工具结果中）", True


def compress(messages: list[dict[str, Any]], budget: TokenBudget | None = None,
             recent_turns: int = 3, tool_result_max_chars: int = 300) -> CompressionResult:
    """把任意消息列表压到预算内。

    优先级：system 永远保留 > 最近 recent_turns 轮原文 > 旧轮抽取式摘要 >
    超长工具结果截断。返回可解释的统计，便于做成本归因。
    """
    b = budget or TokenBudget()
    original = estimate_messages_tokens(messages)
    systems = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]

    keep_recent = others[-recent_turns * 2:] if recent_turns else []
    old = others[: len(others) - len(keep_recent)]

    out: list[dict[str, Any]] = list(systems)
    summarized = 0
    if old:
        chunks = [_extractive_summary(str(m.get("content", ""))) for m in old]
        out.append({"role": "system", "content": "历史会话摘要：" + " / ".join(chunks)})
        summarized = len(old)

    truncated = 0
    for m in keep_recent:
        content = str(m.get("content", ""))
        if m.get("role") == "tool":
            content, hit = truncate_tool_result(content, tool_result_max_chars)
            truncated += int(hit)
        out.append({**m, "content": content})

    # 若仍超预算，从最旧的近期消息开始丢（system 与摘要永不动）
    dropped = 0
    limit = b.total - b.reserve_tools - b.reserve_output - b.reserve_retrieved
    while estimate_messages_tokens(out) > limit and len(out) > len(systems) + 1:
        idx = len(systems) + 1
        out.pop(idx)
        dropped += 1

    return CompressionResult(
        messages=out, original_tokens=original,
        compressed_tokens=estimate_messages_tokens(out),
        dropped_turns=dropped, summarized_turns=summarized,
        truncated_tool_results=truncated,
        summary=next((m["content"] for m in out if str(m.get("content", "")).startswith("历史会话摘要")), ""),
    )


def select_context(blocks: list[dict[str, Any]], budget: TokenBudget | None = None) -> dict[str, Any]:
    """按 priority 排序后在预算内选取上下文块，明确报告被丢弃的块。

    blocks: [{"id", "content", "priority", "kind"}]
    """
    b = budget or TokenBudget()
    limit = max(0, b.total - b.reserve_output)
    ordered = sorted(blocks, key=lambda x: (-int(x.get("priority", 0)), x.get("id", "")))
    selected, dropped, used = [], [], 0
    for blk in ordered:
        cost = estimate_tokens(str(blk.get("content", "")))
        if used + cost <= limit:
            selected.append({**blk, "tokens": cost})
            used += cost
        else:
            dropped.append({"id": blk.get("id"), "tokens": cost,
                            "reason": "over_budget"})
    return {"selected": selected, "dropped": dropped, "tokens_used": used,
            "tokens_limit": limit, "budget": b.report()}


def build_rag_prompt(question: str, passages: list[dict[str, Any]],
                     budget: TokenBudget | None = None) -> dict[str, Any]:
    """带引用编号的 Prompt 拼接：每个段落标 [1][2]…，并预留输出额度。"""
    b = budget or TokenBudget()
    limit = b.reserve_retrieved
    lines, used, kept = [], 0, []
    for i, p in enumerate(passages, 1):
        text = f"[{i}] {p.get('text', '')}"
        cost = estimate_tokens(text)
        if used + cost > limit:
            break
        lines.append(text)
        kept.append({"ref": i, "doc_id": p.get("doc_id"), "chunk_id": p.get("chunk_id"),
                     "tokens": cost})
        used += cost
    prompt = ("请仅依据以下带编号的资料作答，每个事实后标注引用编号；"
              "资料未覆盖的内容明确说明不知道。\n\n"
              + "\n".join(lines) + f"\n\n问题：{question}\n回答：")
    return {"prompt": prompt, "citations": kept, "tokens_used": used,
            "tokens_limit": limit, "estimated_total_tokens": estimate_tokens(prompt)}
