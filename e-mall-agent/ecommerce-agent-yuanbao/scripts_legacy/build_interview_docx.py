# -*- coding: utf-8 -*-
"""生成《LangChain 1.5 电商智能体 · Agent 面试题 100 题》Word 文档。

    python3 scripts/build_interview_docx.py

题库数据：scripts/interview_questions.py（10 章 × 10 题 = 100 题，含详细答案）
输出：docs/LangChain1.5电商智能体_Agent面试题100题.docx
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/data/skills/docx/scripts")

from docxlib import (  # noqa: E402
    ASCII_HANSI,
    EASTASIA,
    add_footer_page_number,
    add_heading,
    add_page_break,
    add_table_double_width,
    add_toc,
    apply_font_to_run,
    ensure_heading_style,
    ensure_yuanbao_defaults,
    open_docx,
    save_docx,
)
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Inches, Pt, RGBColor  # noqa: E402

from interview_questions import CHAPTERS  # noqa: E402

OUT = ROOT / "docs" / "LangChain1.5电商智能体_Agent面试题100题.docx"
BLUE = RGBColor(0x2E, 0x5C, 0x9A)
NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x5A, 0x66, 0x7A)


def para(doc, text, *, style=None, size=11, bold=False, color=None,
         align=None, indent=None, before=0, after=6, font=None):
    p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
    run = p.add_run(text)
    apply_font_to_run(run, eastasia=EASTASIA, ascii=font or ASCII_HANSI,
                      size_pt=size, bold=bold)
    if color is not None:
        run.font.color.rgb = color
    if align is not None:
        p.alignment = align
    if indent is not None:
        p.paragraph_format.left_indent = Inches(indent)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    return p


def heading(doc, text, level=1):
    h = add_heading(doc, text, level=level)
    for r in h.runs:
        apply_font_to_run(r, eastasia=EASTASIA, ascii=ASCII_HANSI,
                          size_pt={1: 16, 2: 13, 3: 12}.get(level, 11), bold=True)
        if level == 1:
            r.font.color.rgb = NAVY
    return h


def table(doc, headers, rows, widths, size=9.5):
    t = add_table_double_width(doc, headers=headers, rows=rows,
                               column_widths_dxa=widths, header_shading="D5E8F0")
    for ri, row in enumerate(t.rows):
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                for r in p.runs:
                    apply_font_to_run(r, eastasia=EASTASIA, ascii=ASCII_HANSI,
                                      size_pt=size, bold=(ri == 0))
    return t


def render_answer(doc, parts):
    for item in parts:
        if item.startswith("L|"):
            p = para(doc, item[2:], style="List Bullet", size=10.5, after=3)
            p.paragraph_format.left_indent = Inches(0.28)
        elif item.startswith("C|"):
            para(doc, item[2:], size=9.5, indent=0.3, before=2, after=4,
                 color=GREY, font="Courier New")
        else:
            para(doc, item, size=10.5, after=5)


def cover(doc):
    para(doc, "Agent 面试题 100 题", size=26, bold=True, color=NAVY,
         align=WD_ALIGN_PARAGRAPH.CENTER, before=90, after=14)
    para(doc, "基于「小栈 · 电商智能体」项目", size=15, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=8)
    para(doc, "LangChain 1.5 create_agent · MCP Tools · Vue 3 · FastAPI",
         size=11.5, color=GREY, align=WD_ALIGN_PARAGRAPH.CENTER, after=40)

    table(doc, ["项目信息", "内容"], [
        ["题目规模", "100 题 / 10 章；每题含问题、难度标签与详细参考答案"],
        ["难度分布", "基础 39 题 · 进阶 14 题 · 实战 23 题 · 设计 24 题"],
        ["版本基线", "langchain 1.5.2 · langchain-core 1.8.4 · Python ≥ 3.11 · FastMCP"],
        ["项目形态", "Vue 3 前端 + Python 3 后端；默认 mock 模式免 API Key 可跑"],
        ["配套交付", "前后端代码 · 97 个 pytest 用例 · Excel 89 条输入/输出用例 · 产品/架构/知识点文档"],
        ["文档日期", "2026 年 11 月 23 日"],
    ], [2200, 7160], size=10)

    para(doc, "所有答案均落到项目里的具体文件、函数、配置、测试或实测踩坑，"
              "不是通用八股；既可用于面试提问，也可作为团队内部的技术复盘提纲。",
         size=10.5, color=GREY, align=WD_ALIGN_PARAGRAPH.CENTER, before=26, after=0)
    add_page_break(doc)


def usage(doc):
    heading(doc, "使用说明", 1)
    para(doc, "本题库按「知识点 → 项目落地 → 边界与生产化」组织，10 章各 10 题，"
              "章内从基础到设计递进。每章开头有一张速览表，可直接挑题；正文每题带"
              "【基础 / 进阶 / 实战 / 设计】标签，方便按候选人层级组合试卷。", size=10.5)
    para(doc, "建议用法：", size=10.5, bold=True, after=3)
    for line in [
        "面试官：初级岗抽第 1、2、3、4 章的基础题；中高级岗加第 5、6、7、8 章的进阶与实战题；架构岗重点用第 9、10 章的设计题追问取舍。",
        "候选人：先能画出 create_agent → ToolNode → ToolMessage 的消息序列，再能解释中间件顺序、thread_id 报错、MCP stdio 环境坑，最后能讲清生产替换清单。",
        "团队复盘：配合 docs/02-技术架构.md 的取舍表与 docs/03-LangChain知识点测试矩阵.md 的四个实测踩坑，逐条对照项目实现。",
    ]:
        p = para(doc, line, style="List Bullet", size=10.5, after=3)
        p.paragraph_format.left_indent = Inches(0.28)

    para(doc, "与配套交付物的对应关系：", size=10.5, bold=True, before=8, after=3)
    table(doc, ["交付物", "内容", "在面试中的用途"], [
        ["backend/ + frontend/", "全量可运行前后端代码", "追问「这段代码在哪、为什么这么写」"],
        ["backend/tests/", "97 个 pytest 用例（54 工程 + 43 知识点专项）", "验证答案里的断言不是口头描述"],
        ["docs/LangChain1.5_电商智能体_测试用例.xlsx", "89 条输入 / 预期输出 / 实测输出", "考察测试用例设计与覆盖矩阵"],
        ["docs/01、02、03 文档", "产品功能 / 技术架构 / 知识点测试矩阵", "考察分层、取舍与踩坑复盘"],
    ], [3300, 3200, 2860], size=9.5)
    add_page_break(doc)


def toc_page(doc):
    heading(doc, "目录", 1)
    para(doc, "目录只列章与附录；每章开头的「本章题目速览」表列出该章 10 题。"
              "在 Word 中打开时如提示更新域，请选择「更新整个目录」（或按 F9）。",
         size=10, color=GREY, after=8)
    add_toc(doc, heading_range="1-1", hyperlink=True)
    add_page_break(doc)


def chapters(doc):
    n = 0
    for name, intro, questions in CHAPTERS:
        heading(doc, name, 1)
        para(doc, intro, size=10.5, color=GREY, after=10)

        overview = []
        offset = n
        for i, (q, level, _) in enumerate(questions, 1):
            overview.append([f"Q{offset + i}", q, level])
        table(doc, ["题号", "题目", "难度"], overview, [1100, 6900, 1360], size=9)

        for q, level, parts in questions:
            n += 1
            heading(doc, f"Q{n} · {q}　【{level}】", 2)
            para(doc, "参考答案", size=10.5, bold=True, color=BLUE, after=4)
            render_answer(doc, parts)
        add_page_break(doc)


def appendix_a(doc):
    heading(doc, "附录 A · 12 个 LangChain 知识点 → 题号索引", 1)
    para(doc, "下表把项目里 test_langchain_knowledge_points.py 的 kp1~kp12 与本题库题号对齐，"
              "可用于「按知识点组卷」。Excel 用例集的覆盖矩阵显示 12/12 双层覆盖。",
         size=10.5, color=GREY, after=8)
    rows = [
        ["kp1", "create_agent / Agent 循环", "Q1、Q2、Q10–Q20、Q91"],
        ["kp2", "BaseChatModel / bind_tools / Function Calling", "Q21–Q26、Q30"],
        ["kp3", "@tool / args_schema 参数校验", "Q31、Q40、Q82"],
        ["kp4", "MCPAdapter / MCPConfig / 降级", "Q32–Q39、Q92"],
        ["kp5", "AgentMiddleware / 内置中间件", "Q41–Q50、Q84–Q88"],
        ["kp6", "response_format / 三种 Strategy", "Q51–Q60"],
        ["kp7", "checkpointer / thread_id / 多轮记忆", "Q61–Q70"],
        ["kp8", "astream_events / SSE / 流式前端", "Q71–Q80"],
        ["kp9", "标准内容块 / ToolMessage / 卡片", "Q8、Q14、Q77、Q79、Q83"],
        ["kp10", "init_chat_model / provider:model", "Q27–Q29"],
        ["kp11", "LangGraph 运行时 / recursion_limit", "Q1、Q19、Q20、Q91、Q92"],
        ["kp12", "1.5 版本特性（Decisions / Router / 内置 MCP）", "Q4–Q9、Q50、Q68、Q97"],
    ]
    table(doc, ["知识点", "核心 API / 概念", "对应题号"], rows,
          [1400, 5200, 2760], size=9.5)
    add_page_break(doc)


def appendix_b(doc):
    heading(doc, "附录 B · 项目速查表", 1)
    para(doc, "面试时可直接用这张表核对候选人说的是不是本项目里的真实实现。",
         size=10.5, color=GREY, after=8)
    rows = [
        ["版本基线", "langchain 1.5.2 / core 1.8.4 / Python 3.11+ / FastMCP", "backend/requirements.txt"],
        ["Agent 组装", "create_agent(model, tools, system_prompt, middleware, checkpointer, name)", "backend/app/agent/builder.py"],
        ["MCP 工具", "10 个只读工具，stdio 或 Streamable HTTP，三级降级", "mcp_server/server.py · agent/mcp_tools.py"],
        ["中间件", "PromptGuard → ToolAudit → ModelCallLimit → ToolCallLimit → ModelRetry", "backend/app/agent/middleware.py"],
        ["结构化输出", "ToolStrategy(PurchaseIntent)，仅 real 模式挂载", "builder.py · schemas.py · api/routes.py"],
        ["会话记忆", "InMemorySaver + configurable.thread_id + recursion_limit=24", "runtime._config_for()"],
        ["SSE 事件", "meta / token / tool_start / tool_end / cards / error / done", "runtime.stream_events() · schemas.SSEEvent"],
        ["HTTP 接口", "8 个：health / tools / products / audit / chat / chat-sync / intent / sessions", "backend/app/api/routes.py"],
        ["测试", "后端 97 例 + 前端 12 例 + 零依赖 8 断言 + Excel 89 条", "backend/tests/ · frontend/ · docs/"],
        ["四个实测踩坑", "缺 thread_id 报错 / ToolStrategy 递归 / stdio PYTHONPATH / tool-call-delta", "docs/03-LangChain知识点测试矩阵.md"],
        ["启动命令", "uvicorn app.main:app --port 8000；前端 npm run dev", "README.md 第 2 节"],
        ["演示问题", "检索 / 算价 / 查单 / 售后 / 推荐 / 注入拦截，共 6 个", "README.md 第 7 节"],
    ]
    table(doc, ["项目", "关键值 / 结论", "位置"], rows,
          [2100, 4900, 2360], size=9.5)

    para(doc, "一句话总结这套架构：领域规则下沉到纯 Python 层保证事实正确，"
              "MCP 负责工具复用，create_agent 负责编排，中间件负责不管模型听不听都生效的治理，"
              "卡片数据直接取自 ToolMessage 避免模型改写数字，前端只做协议归约与可视化。",
         size=10.5, bold=True, color=NAVY, before=12, after=6)


def main():
    doc = open_docx()
    ensure_yuanbao_defaults(doc)
    ensure_heading_style(doc, level=1, size_pt=17, bold=True)
    ensure_heading_style(doc, level=2, size_pt=12.5, bold=True)

    section = doc.sections[0]
    hp = section.header.paragraphs[0]
    hr = hp.add_run("小栈 · 电商智能体　|　LangChain 1.5 Agent 面试题 100 题")
    apply_font_to_run(hr, eastasia=EASTASIA, ascii=ASCII_HANSI, size_pt=9)
    hr.font.color.rgb = GREY
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_footer_page_number(section, prefix="第 ", suffix=" 页")

    cover(doc)
    usage(doc)
    toc_page(doc)
    chapters(doc)
    appendix_a(doc)
    appendix_b(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    save_docx(doc, OUT)
    print("saved:", OUT)
    print("chapters:", len(CHAPTERS), "questions:", sum(len(q) for _, _, q in CHAPTERS))


if __name__ == "__main__":
    main()
