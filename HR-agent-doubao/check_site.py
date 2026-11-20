"""编译产物自检：跑完 build_site.py 后执行，确认没有漏掉的 markdown 标记。

用法：python check_site.py
"""
import pathlib, re, sys

SITE = pathlib.Path(__file__).resolve().parent / "site"
if not SITE.exists():
    sys.exit("site/ 不存在，先跑 build_site.py")

pages = sorted(SITE.glob("*.html"))
bad = []
for p in pages:
    t = p.read_text(encoding="utf-8")
    # 只检查"代码块之外"的正文，避免把代码块里的 ## / ``` 当成漏渲染
    body_only = re.sub(r"(?s)<pre>.*?</pre>", "", t)
    checks = {
        "裸代码围栏": body_only.count("```"),
        "裸标题井号": len(re.findall(r"(?m)^#{2,6} ", body_only)),
        "裸表格行": len(re.findall(r"(?m)^\|.*\|$", body_only)),
        "未闭合 pre": t.count("<pre>") - t.count("</pre>"),
        "未闭合 table": t.count("<table>") - t.count("</table>"),
        "侧栏当前页": t.count('class="cur"'),
        "正文": t.count('<article class="doc">'),
    }
    print(f"{p.name:<40} " + "  ".join(f"{k}={v}" for k, v in checks.items()))
    if checks["裸代码围栏"] or checks["裸标题井号"] or checks["裸表格行"] \
            or checks["未闭合 pre"] or checks["未闭合 table"] \
            or checks["侧栏当前页"] != 1 or checks["正文"] != 1:
        bad.append(p.name)

print()
if bad:
    print("❌ 有问题的页面：", ", ".join(bad))
    sys.exit(1)
print(f"✓ {len(pages)} 个页面全部通过结构自检")
