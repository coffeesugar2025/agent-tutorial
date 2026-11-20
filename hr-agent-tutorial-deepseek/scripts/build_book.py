"""把 18 章与附录合并成一个便于离线阅读/打印的 Markdown 文件。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

CHAPTERS = [
    "00-course-map.md",
    "01-llm-prompt.md",
    "02-agent-loop.md",
    "03-tool-calling.md",
    "04-planning.md",
    "05-workflow.md",
    "06-memory.md",
    "07-context-engineering.md",
    "08-rag-basics.md",
    "09-rag-advanced.md",
    "10-knowledge-graph.md",
    "11-reliability.md",
    "12-hitl-security.md",
    "13-multi-agent.md",
    "14-sandbox-longtask.md",
    "15-observability-eval.md",
    "16-capstone.md",
    "17-career.md",
]
APPENDICES = [
    "appendix/glossary.md",
    "appendix/langchain.md",
    "appendix/model-engineering.md",
    "appendix/ecosystem.md",
]


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def title_of(text: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+)$", text)
    return match.group(1).strip() if match else fallback


def main() -> None:
    chapters = []
    for name in CHAPTERS:
        text = strip_frontmatter((DOCS / name).read_text(encoding="utf-8"))
        chapters.append((name, text, title_of(text, name)))
    appendices = []
    for name in APPENDICES:
        text = strip_frontmatter((DOCS / name).read_text(encoding="utf-8"))
        appendices.append((name, text, title_of(text, name)))

    lines = [
        "# HR Agent 实战教程（单文件版）",
        "",
        "> 本文件由 `docs/` 下 18 章与 4 篇附录自动合并，方便离线阅读、打印或导入笔记软件。",
        "> 代码与可运行 demo 请回到仓库查看：`code/chXX_*.py`、`app/backend/`、`app/frontend/`。",
        "> 全书 demo 基于 **LangChain 1.x + LangGraph 1.x**，默认离线 `MockChatModel`，可切换真实模型。",
        "",
        "## 目录",
        "",
    ]
    for index, (_, _, title) in enumerate(chapters):
        lines.append(f"{index}. {title}")
    lines.append("")
    lines.append("### 附录")
    lines.append("")
    for index, (_, _, title) in enumerate(appendices):
        lines.append(f"{index + 1}. {title}")
    lines.append("")

    lines.append("\n---\n")
    for _, text, _ in chapters:
        lines.append(text.rstrip())
        lines.append("\n---\n")
    for _, text, _ in appendices:
        lines.append(text.rstrip())
        lines.append("\n---\n")

    output = DOCS / "ALL_IN_ONE.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output} ({output.stat().st_size / 1024:.0f} KB, {sum(len(t) for _, t, _ in chapters) + sum(len(t) for _, t, _ in appendices)} chars)")


if __name__ == "__main__":
    main()
