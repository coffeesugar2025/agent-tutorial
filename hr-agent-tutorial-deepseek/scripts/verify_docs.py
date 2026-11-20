"""检查教程文档结构、frontmatter 与代码文件是否齐全。

用法：
    python scripts/verify_docs.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

PART_0 = "启程：从 HR 痛点理解 Agent"
PART_1 = "单 Agent 核心"
PART_2 = "RAG 与知识工程"
PART_3 = "生产级可靠性"
PART_4 = "项目实战与求职"


@dataclass(frozen=True)
class Chapter:
    order: int
    slug: str
    file: str
    part: str
    code: str | None


CHAPTERS = [
    Chapter(0, "course-map", "00-course-map.md", PART_0, "ch00_hello_agent.py"),
    Chapter(1, "llm-prompt", "01-llm-prompt.md", PART_0, "ch01_structured_output.py"),
    Chapter(2, "agent-loop", "02-agent-loop.md", PART_1, "ch02_agent_loop.py"),
    Chapter(3, "tool-calling", "03-tool-calling.md", PART_1, "ch03_tools.py"),
    Chapter(4, "planning", "04-planning.md", PART_1, "ch04_planning.py"),
    Chapter(5, "workflow", "05-workflow.md", PART_1, "ch05_workflow.py"),
    Chapter(6, "memory", "06-memory.md", PART_1, "ch06_memory.py"),
    Chapter(7, "context-engineering", "07-context-engineering.md", PART_1, "ch07_context.py"),
    Chapter(8, "rag-basics", "08-rag-basics.md", PART_2, "ch08_rag_basic.py"),
    Chapter(9, "rag-advanced", "09-rag-advanced.md", PART_2, "ch09_rag_advanced.py"),
    Chapter(10, "knowledge-graph", "10-knowledge-graph.md", PART_2, "ch10_text2sql.py"),
    Chapter(11, "reliability", "11-reliability.md", PART_3, "ch11_reliability.py"),
    Chapter(12, "hitl-security", "12-hitl-security.md", PART_3, "ch12_hitl.py"),
    Chapter(13, "multi-agent", "13-multi-agent.md", PART_3, "ch13_multi_agent.py"),
    Chapter(14, "sandbox-longtask", "14-sandbox-longtask.md", PART_3, "ch14_sandbox.py"),
    Chapter(15, "observability-eval", "15-observability-eval.md", PART_3, "ch15_eval.py"),
    Chapter(16, "capstone", "16-capstone.md", PART_4, None),
    Chapter(17, "career", "17-career.md", PART_4, None),
]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end].strip()
    meta: dict = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        value = raw.strip()
        if value.startswith("["):
            try:
                meta[key.strip()] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, text[end + 4 :]


def chinese_chars(text: str) -> int:
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    return len(re.findall(r"[\u4e00-\u9fff]", body))


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[tuple[str, str, str, str]] = []

    for chapter in CHAPTERS:
        path = DOCS / chapter.file
        if not path.exists():
            errors.append(f"[{chapter.order:02d}] 缺少文档：{path.relative_to(ROOT)}")
            rows.append((f"{chapter.order:02d}", "MISSING", "-", "-"))
            continue

        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        for key in ("title", "slug", "order", "part", "minutes", "difficulty", "prerequisites", "summary"):
            if key not in meta:
                errors.append(f"[{chapter.order:02d}] frontmatter 缺少 {key}")
        if str(meta.get("order")) != str(chapter.order):
            errors.append(f"[{chapter.order:02d}] order 应为 {chapter.order}，实际 {meta.get('order')}")
        if meta.get("slug") != chapter.slug:
            errors.append(f"[{chapter.order:02d}] slug 应为 {chapter.slug}，实际 {meta.get('slug')}")
        if meta.get("part") != chapter.part:
            errors.append(f"[{chapter.order:02d}] part 应为 {chapter.part}，实际 {meta.get('part')}")

        headings = len(re.findall(r"^##\s+\d+\.", body, flags=re.M))
        chars = chinese_chars(body)
        if headings < 6:
            errors.append(f"[{chapter.order:02d}] 结构化小节过少：{headings}（至少 6）")
        if chars < 2500:
            errors.append(f"[{chapter.order:02d}] 正文汉字数偏少：{chars}（目标 3000+）")

        if chapter.code:
            code_path = ROOT / "code" / chapter.code
            if not code_path.exists():
                errors.append(f"[{chapter.order:02d}] 缺少代码：code/{chapter.code}")
                code_state = "MISSING"
            else:
                try:
                    compile(code_path.read_text(encoding="utf-8"), str(code_path), "exec")
                    code_state = "OK"
                except SyntaxError as exc:
                    errors.append(f"[{chapter.order:02d}] 语法错误 {chapter.code}: {exc}")
                    code_state = "SYNTAX"
        else:
            code_state = "APP"

        rows.append((f"{chapter.order:02d}", f"{chars} 字", f"{headings} 节", code_state))

    glossary = DOCS / "appendix" / "glossary.md"
    if not glossary.exists():
        errors.append("缺少 docs/appendix/glossary.md")
    else:
        count = chinese_chars(glossary.read_text(encoding="utf-8"))
        if count < 1500:
            warnings.append(f"术语表汉字数偏少：{count}")

    print(f"{'章节':<5}{'正文':<12}{'结构':<8}{'代码'}")
    print("-" * 40)
    for row in rows:
        print(f"{row[0]:<5}{row[1]:<12}{row[2]:<8}{row[3]}")

    print()
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"\n合计：{len(CHAPTERS)} 章，错误 {len(errors)}，警告 {len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
