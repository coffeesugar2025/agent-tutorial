"""
把 docs/*.md 编译成一套可离线阅读的 HTML 书（带侧边目录、章节导航）。

用法：
    python build_site.py            # 输出到 site/
    python build_site.py --open     # 编译后用浏览器打开

不依赖任何第三方库：自带的 markdown 转换器覆盖本书用到的全部语法
（标题、段落、有序/无序列表、代码块、行内代码、加粗、链接、表格、引用、分隔线）。
"""

from __future__ import annotations

import html
import re
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
SITE = ROOT / "site"

# ---------------------------------------------------------------- 基础工具
def esc(s: str) -> str:
    return html.escape(s, quote=False)


INLINE_CODE = re.compile(r"`([^`]+)`")


def inline(s: str) -> str:
    """行内格式：先保护行内代码，再处理加粗与链接。"""
    slots: list[str] = []

    def stash(m):
        slots.append(f"<code>{esc(m.group(1))}</code>")
        return f"\x00{len(slots) - 1}\x00"

    s = INLINE_CODE.sub(stash, s)
    s = esc(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: link(m.group(1), m.group(2)), s)
    s = re.sub(r"(?<![\w<])\*([^*\s][^*]*)\*", r"<em>\1</em>", s)
    for i, code in enumerate(slots):
        s = s.replace(f"\x00{i}\x00", code)
    return s


def link(text: str, target: str) -> str:
    """把 .md 链接改写成 .html，外部链接加 target。"""
    if target.startswith(("http://", "https://", "#")):
        return f'<a href="{esc(target)}" target="_blank" rel="noopener">{text}</a>'
    t = target.split("#")[0]
    if t.endswith(".md"):
        t = t.rsplit("/", 1)[-1][:-3] + ".html"
        return f'<a href="{esc(t)}">{text}</a>'
    return f'<a href="{esc(target)}">{text}</a>'


# ---------------------------------------------------------------- markdown
def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    list_open = None          # "ul" / "ol"

    def close_list():
        nonlocal list_open
        if list_open:
            out.append(f"</{list_open}>")
            list_open = None

    while i < n:
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            close_list()
            lang = line.strip()[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(buf)
            cls = f' class="lang-{esc(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{esc(code)}</code></pre>")
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_list()
            lvl = len(m.group(1))
            text = m.group(2).strip()
            anchor = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)[:48].strip("-")
            out.append(f'<h{lvl} id="{esc(anchor)}">{inline(text)}</h{lvl}>')
            i += 1
            continue

        # 分隔线
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            close_list()
            out.append("<hr>")
            i += 1
            continue

        # 表格
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1]):
            close_list()
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append('<table><thead><tr>' +
                       "".join(f"<th>{inline(c)}</th>" for c in header) +
                       "</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
            continue

        # 引用
        if line.strip().startswith(">"):
            close_list()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f'<blockquote>{inline(" ".join(buf))}</blockquote>')
            continue

        # 列表
        m_ul = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        m_ol = re.match(r"^(\s*)\d+[.)]\s+(.*)$", line)
        if m_ul or m_ol:
            want = "ul" if m_ul else "ol"
            if list_open != want:
                close_list()
                out.append(f"<{want}>")
                list_open = want
            text = (m_ul or m_ol).group(2).strip()
            out.append(f"<li>{inline(text)}</li>")
            i += 1
            continue

        # 空行
        if not line.strip():
            close_list()
            i += 1
            continue

        # 段落（合并连续非空行）
        close_list()
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|```|>|\s*[-*+]\s|\s*\d+[.)]\s)", lines[i]):
            if "|" in lines[i]:
                break
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")

    close_list()
    return "\n".join(out)


# ---------------------------------------------------------------- 版式
PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · HR Agent 工程实战教程</title>
<style>
{style}
</style></head><body>
<aside class="side">
  <div class="brand"><a href="index.html">HR Agent 工程实战教程</a>
    <span>Python 3.12 · Vue 3 · HR 场景</span></div>
  <nav>{nav}</nav>
</aside>
<main>
  <article class="doc">{body}</article>
  <footer class="pager">{pager}</footer>
  <div class="foot">本教程示例数据均为虚构，仅用于教学。</div>
</main>
</body></html>
"""

STYLE = """
:root{--bg:#fbfcfc;--fg:#1a1f23;--muted:#657076;--line:#e3e8ea;--brand:#0f766e;
      --brand-soft:#e8f4f2;--code-bg:#11202b;--code-fg:#dfe9ee}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);
     font:16px/1.75 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
.side{position:fixed;top:0;left:0;bottom:0;width:280px;overflow-y:auto;
      border-right:1px solid var(--line);background:#fff;padding:20px 16px 40px}
.brand a{display:block;font-weight:700;font-size:15px;line-height:1.4}
.brand span{display:block;color:var(--muted);font-size:12px;margin-top:4px}
nav{margin-top:18px;font-size:14px}
nav a{display:block;padding:5px 8px;border-radius:6px;color:#33414a;line-height:1.45}
nav a:hover{background:#f2f6f7;text-decoration:none}
nav a.cur{background:var(--brand-soft);color:#0b5d56;font-weight:600}
nav .grp{margin:14px 0 4px;font-size:11.5px;letter-spacing:.06em;color:#9aa5aa;
          text-transform:uppercase;padding-left:8px}
main{margin-left:280px;padding:44px 48px 80px;max-width:920px}
.doc h1{font-size:27px;line-height:1.35;margin:0 0 6px;letter-spacing:-.01em}
.doc h1+p{color:var(--muted)}
.doc h2{font-size:20px;margin:38px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.doc h3{font-size:17px;margin:26px 0 10px}
.doc h4{font-size:15px;margin:20px 0 8px;color:#33414a}
.doc p{margin:12px 0}
.doc ul,.doc ol{margin:12px 0;padding-left:24px}
.doc li{margin:5px 0}
.doc blockquote{margin:16px 0;padding:12px 16px;background:#f5f8f8;border-left:3px solid var(--brand);
                border-radius:0 8px 8px 0;color:#3d4a51}
.doc blockquote p{margin:0}
.doc pre{background:var(--code-bg);color:var(--code-fg);padding:14px 16px;border-radius:10px;
         overflow-x:auto;font:13.5px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;
         margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.doc code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13.5px;
          background:#eef3f4;padding:1px 5px;border-radius:4px}
.doc pre code{background:none;padding:0;color:inherit;font-size:inherit}
.doc table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14.5px}
.doc th,.doc td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
.doc th{background:#f3f7f7;font-weight:600}
.doc hr{border:none;border-top:1px solid var(--line);margin:32px 0}
.doc img{max-width:100%}
.pager{display:flex;justify-content:space-between;gap:16px;margin-top:48px;
       padding-top:20px;border-top:1px solid var(--line);font-size:14px}
.pager a{display:block;padding:10px 14px;border:1px solid var(--line);border-radius:8px;
         max-width:46%;background:#fff}
.pager .nx{text-align:right;margin-left:auto}
.foot{margin-top:36px;color:#a4adb2;font-size:12px}
@media(max-width:860px){
  .side{position:static;width:auto;border-right:none;border-bottom:1px solid var(--line)}
  main{margin:0;padding:24px 18px 60px}
  .doc h1{font-size:23px}
}
"""


# ---------------------------------------------------------------- 组装
TITLES = {}   # 文件名 -> (标题, 分组)


def parse_title(md: str) -> str:
    for line in md.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return "未命名"


def collect():
    files = []
    if (ROOT / "README.md").exists():
        files.append(ROOT / "README.md")
    files += sorted(DOCS.glob("*.md"), key=lambda p: p.name)
    return files


def group_of(name: str) -> str:
    n = name[:2]
    if n in ("00", "01", "02"):
        return "一 · 打地基"
    if n in ("03", "04", "05", "06"):
        return "二 · Agent 内核"
    if n in ("07", "08"):
        return "三 · 记忆与上下文"
    if n in ("09", "10", "11"):
        return "四 · RAG 与知识"
    if n in ("12", "13", "14"):
        return "五 · 协作与生态"
    if n in ("15", "16", "17"):
        return "六 · 生产级可靠性"
    return "七 · 交付与落地"


def build():
    SITE.mkdir(exist_ok=True)
    files = collect()
    pages = []
    for f in files:
        md = f.read_text(encoding="utf-8")
        title = parse_title(md)
        pages.append({"path": f, "md": md, "title": title,
                      "out": ("index.html" if f.name == "README.md"
                              else f.stem + ".html"),
                      "group": "总目录" if f.name == "README.md" else group_of(f.stem)})

    # 侧边导航
    nav_parts, last_group = [], None
    for p in pages:
        if p["group"] != last_group:
            nav_parts.append(f'<div class="grp">{esc(p["group"])}</div>')
            last_group = p["group"]
        nav_parts.append(f'<a href="{p["out"]}" data-href="{p["out"]}">{esc(p["title"])}</a>')
    nav = "\n".join(nav_parts)

    for idx, p in enumerate(pages):
        prev = pages[idx - 1] if idx > 0 else None
        nxt = pages[idx + 1] if idx + 1 < len(pages) else None
        pager = []
        if prev:
            pager.append(f'<a class="pr" href="{prev["out"]}">← {esc(prev["title"])}</a>')
        else:
            pager.append("<span></span>")
        if nxt:
            pager.append(f'<a class="nx" href="{nxt["out"]}">{esc(nxt["title"])} →</a>')
        body = md_to_html(p["md"])
        body = body.replace('<a href="index.html"',
                            '<a href="index.html"')
        out_html = PAGE.format(title=esc(p["title"]), style=STYLE, nav=nav,
                               body=body, pager="\n".join(pager))
        # 标记当前页
        out_html = out_html.replace(
            f'data-href="{p["out"]}"',
            f'data-href="{p["out"]}" class="cur"')
        (SITE / p["out"]).write_text(out_html, encoding="utf-8")
        print(f"  生成 {p['out']:<42} {p['title']}")

    print(f"\n完成：{len(pages)} 个页面 → {SITE}")


if __name__ == "__main__":
    print("编译 markdown → HTML ...")
    build()
    index = SITE / "index.html"
    if "--open" in sys.argv:
        webbrowser.open(index.as_uri())
    else:
        print(f"双击打开：{index}")
