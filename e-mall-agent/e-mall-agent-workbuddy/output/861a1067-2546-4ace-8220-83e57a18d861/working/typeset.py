# -*- coding: utf-8 -*-
"""Mechanical doc-typeset: Markdown draft -> compliant full HTML."""
import html
import json
import re
from pathlib import Path

ROOT = Path(r"C:\Users\a1572\WorkBuddy\2026-11-22-16-26-05")
REQ = ROOT / "output" / "861a1067-2546-4ace-8220-83e57a18d861"
MD = REQ / "stage1" / "final_draft.md"
TOKENS = Path(r"C:\Users\a1572\.workbuddy\plugins\cache\workbuddy-builtin\workbuddy-docx\5.11.3-wb.43806934.gecace0f7.ha395516167d4\skills\design-token\tokens\compiled\general.json")
OUT = REQ / "stage2" / "formatted-电商智能体Agent面试题100问.html"

token_data = json.loads(TOKENS.read_text(encoding="utf-8"))
OUT.parent.mkdir(parents=True, exist_ok=True)


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def esc(text: str) -> str:
    return html.escape(text, quote=False)


lines = MD.read_text(encoding="utf-8").splitlines()
doc_title = ""
chapters = []
cur_chapter = None
cur_question = None
block = []
code = False
code_buf = []


def flush_block():
    global block
    if not block or cur_question is None:
        block = []
        return
    text = " ".join(x.strip() for x in block).strip()
    block = []
    if not text:
        return
    cur_question["body"].append(("p", text))


for raw in lines:
    line = raw.rstrip()
    if line.startswith("# ") and not doc_title:
        doc_title = line[2:].strip()
        continue
    if code:
        if line.startswith("```"):
            code = False
            cur_question["body"].append(("code", "\n".join(code_buf)))
            code_buf = []
        else:
            code_buf.append(raw)
        continue
    if line.startswith("```"):
        flush_block()
        code = True
        code_buf = []
        continue
    if line.startswith("## "):
        flush_block()
        cur_chapter = {"title": line[3:].strip(), "questions": []}
        chapters.append(cur_chapter)
        cur_question = None
        continue
    if line.startswith("### Q"):
        flush_block()
        m = re.match(r"### Q(\d+)\.\s*(.+)", line)
        num, title = (m.group(1), m.group(2)) if m else ("?", line[4:])
        cur_question = {"num": num, "title": title, "body": []}
        cur_chapter["questions"].append(cur_question)
        continue
    if not line.strip():
        flush_block()
        continue
    if re.match(r"^\d+\.\s+", line):
        flush_block()
        cur_question["body"].append(("li", re.sub(r"^\d+\.\s+", "", line)))
        continue
    if line.startswith("- "):
        flush_block()
        cur_question["body"].append(("ul", line[2:]))
        continue
    block.append(line)
flush_block()

# TOC entries: chapter h1 + all question h2 entries
toc_items = []
for ci, ch in enumerate(chapters, 1):
    subs = [(f"q-{q['num']}", f"Q{q['num']}. {q['title']}") for q in ch["questions"]]
    toc_items.append((f"section-{ci}", ch["title"], subs))

toc_html = []
for anchor, title, subs in toc_items:
    toc_html.append(f'<li><a href="#{anchor}">{esc(title)}</a>')
    if subs:
        toc_html.append("<ol>")
        for sa, st in subs:
            toc_html.append(f'<li><a href="#{sa}">{esc(st)}</a></li>')
        toc_html.append("</ol>")
    toc_html.append("</li>")

body_parts = []
P = ('style="font-family:var(--ff-body);font-size:var(--fs-body);line-height:var(--lh-body);'
     'text-indent:var(--indent-body);margin:var(--spacing-paragraph) 0;color:var(--color-text);'
     'text-align:justify"')
LI = ('style="font-family:var(--ff-body);font-size:var(--fs-body);line-height:var(--lh-body);'
      'margin:var(--spacing-list) 0;color:var(--color-text)"')
H1 = ('style="font-family:var(--ff-heading);font-size:var(--fs-h1);font-weight:var(--fw-bold);'
      'line-height:var(--lh-heading);color:var(--color-primary);margin:var(--spacing-section) 0 '
      'var(--spacing-paragraph) 0;text-align:left"')
H2 = ('style="font-family:var(--ff-heading);font-size:var(--fs-h2);font-weight:var(--fw-bold);'
      'line-height:var(--lh-heading);color:var(--color-heading);margin:var(--spacing-block) 0 '
      'var(--spacing-paragraph) 0;text-align:left"')
PRE = ('style="font-family:var(--ff-mono);font-size:var(--fs-small);line-height:var(--lh-body);'
       'background:var(--color-code-bg);padding:var(--spacing-paragraph);margin:var(--spacing-paragraph) 0;'
       'color:var(--color-text)"')

for ci, ch in enumerate(chapters, 1):
    body_parts.append(f'<div class="chapter"><h1 id="section-{ci}" {H1}>{esc(ch["title"])}</h1>')
    for q in ch["questions"]:
        body_parts.append(f'<h2 id="q-{q["num"]}" {H2}>{esc("Q" + q["num"] + ". " + q["title"])}</h2>')
        pending = None
        for kind, content in q["body"]:
            if kind == "p":
                if pending:
                    body_parts.append(f"</{pending}>")
                    pending = None
                body_parts.append(f"<p {P}>{inline(content)}</p>")
            elif kind == "code":
                if pending:
                    body_parts.append(f"</{pending}>")
                    pending = None
                body_parts.append(f"<pre {PRE}><code>{esc(content)}</code></pre>")
            elif kind in ("li", "ul"):
                tag = "ol" if kind == "li" else "ul"
                if pending != tag:
                    if pending:
                        body_parts.append(f"</{pending}>")
                    body_parts.append(f"<{tag}>")
                    pending = tag
                body_parts.append(f"<li {LI}>{inline(content)}</li>")
        if pending:
            body_parts.append(f"</{pending}>")
    body_parts.append("</div>")
body_parts.append(f'<p {P}>—— 全文完 ——</p>')

css_vars = token_data["css_variables"]
extra = {
    "--ff-body": '"Microsoft YaHei", "微软雅黑", sans-serif',
    "--ff-heading": '"Microsoft YaHei", "微软雅黑", sans-serif',
    "--ff-mono": '"Consolas", "Courier New", monospace',
    "--fs-h1": "18pt",
    "--fs-h2": "14pt",
    "--fs-body": "12pt",
    "--fs-small": "10.5pt",
    "--fs-cover-title": "28pt",
    "--lh-body": "1.7",
    "--lh-heading": "1.35",
    "--fw-bold": "700",
    "--color-primary": "#2563EB",
    "--color-heading": "#111827",
    "--color-text": "#212121",
    "--color-muted": "#6B7280",
    "--color-code-bg": "#F5F7FA",
    "--spacing-paragraph": "0.55em",
    "--spacing-block": "1.25em",
    "--spacing-section": "2em",
    "--spacing-list": "0.35em",
    "--indent-body": "2em",
    "--page-content-width": "15.6cm",
}
var_lines = "\n".join(f"  {k}: {v};" for k, v in {**css_vars, **extra}.items())
# keep token names but override unsafe first font in semantic aliases

html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="docx-page-size" content="A4">
<title>{esc(doc_title)}</title>
<style>
:root {{
{var_lines}
}}
@page {{
  margin: 2.5cm 2.5cm 2.2cm 2.5cm;
  @bottom-center {{ content: counter(page); }}
}}
@page cover {{
  @bottom-center {{ content: none; }}
}}
section[role="cover"] {{ page: cover; }}
body {{
  max-width: var(--page-content-width);
  margin-left: auto;
  margin-right: auto;
  font-family: var(--ff-body);
  font-size: var(--fs-body);
  color: var(--color-text);
}}
.cover-title {{
  font-family: var(--ff-heading);
  font-size: var(--fs-cover-title);
  font-weight: var(--fw-bold);
  color: var(--color-primary);
  text-align: center;
  margin-top: var(--spacing-section);
}}
.cover-subtitle {{
  font-family: var(--ff-body);
  font-size: var(--fs-h2);
  color: var(--color-muted);
  text-align: center;
  margin-top: var(--spacing-paragraph);
}}
.cover-meta {{
  font-family: var(--ff-body);
  font-size: var(--fs-body);
  color: var(--color-muted);
  text-align: center;
  margin-top: var(--spacing-section);
}}
.toc-title {{
  font-family: var(--ff-heading);
  font-size: var(--fs-h1);
  font-weight: var(--fw-bold);
  color: var(--color-primary);
  text-align: center;
}}
.toc-list, .toc-list ol, .toc-list ul {{ list-style: none; }}
.toc-list li {{
  font-family: var(--ff-body);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  margin: var(--spacing-list) 0;
  color: var(--color-text);
}}
.toc-list a {{ color: var(--color-text); }}
code {{ font-family: var(--ff-mono); font-size: var(--fs-small); color: var(--color-text); }}
strong {{ font-weight: var(--fw-bold); }}
</style>
</head>
<body>
<section role="cover">
  <p class="cover-title">{esc(doc_title)}</p>
  <p class="cover-subtitle">基于 LangChain 1.5 电商智能体项目的 100 组面试问答</p>
  <p class="cover-meta">覆盖 Agent、LangGraph、MCP、RAG、上下文工程、权限与可观测性</p>
</section>
<section role="cover">
<nav class="doc-toc" aria-label="文档目录">
  <p class="toc-title">目录</p>
  <ol class="toc-list">
  {''.join(toc_html)}
  </ol>
</nav>
</section>
<section role="body" data-page-restart="1">
{''.join(body_parts)}
</section>
</body>
</html>
"""
OUT.write_text(html_doc, encoding="utf-8")
print(json.dumps({"output": str(OUT), "chapters": len(chapters),
                  "questions": sum(len(c["questions"]) for c in chapters),
                  "bytes": OUT.stat().st_size}, ensure_ascii=False))
