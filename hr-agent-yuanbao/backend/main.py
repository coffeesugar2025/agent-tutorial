"""FastAPI 聚合服务：把 16 个 LangChain / LangGraph Demo 挂成统一 API。

设计要点（教程反复强调的工程习惯）：
  - 章节元数据由后端下发，前端按 schema 自动渲染表单，新增一章不用改前端
  - 统一契约 POST /api/demo/{id} → {answer, steps, metrics, state, hitl}
  - 动态导入：每章独立入口，删掉任一目录只影响那一章
  - HITL 恢复：ch04 与 ch16 都用 LangGraph interrupt + checkpointer，
    前端回传 case_id 即命中 thread_id 对应的断点
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import config, hr_data, ollama_client  # noqa: E402
from common.schema import ApproveRequest, DemoRequest  # noqa: E402

app = FastAPI(title="HR Agent 教学控制台 · LangChain 版", version="2.0.0",
              description="Python 3.12 + LangChain / LangGraph + Vue3 的 Agent 全链路教程")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GROUPS = ["入门：LCEL / 循环与工具", "决策与流程：StateGraph", "上下文与知识：Retriever",
          "协作与扩展：MCP / Multi-Agent", "生产化：护栏 / 评测 / 模型工程", "综合：LangGraph 全链路"]

CHAPTER_META: list[dict[str, Any]] = [
    {"id": "ch01_loop", "no": 1, "title": "Agent Loop（LCEL vs StateGraph）", "group": GROUPS[0],
     "brief": "LCEL 一次问答 vs LangGraph 条件边循环，recursion_limit 与预算双刹车。",
     "fields": [{"key": "question", "label": "用户问题", "type": "text", "default": "我今年还剩几天年假？"},
                {"key": "max_steps", "label": "最大步数", "type": "number", "default": 4},
                {"key": "token_budget", "label": "Token 预算", "type": "number", "default": 800}]},
    {"id": "ch02_toolcall", "no": 2, "title": "Tool Calling（@tool + bind_tools + ToolNode）", "group": GROUPS[0],
     "brief": "StructuredTool 自动生成 JSON Schema，模型只出意图，ToolNode 执行并回灌 ToolMessage。",
     "fields": [{"key": "question", "label": "用户问题", "type": "text", "default": "我今年还剩几天年假？"},
                {"key": "emp_id", "label": "工号", "type": "text", "default": "E1001"}]},
    {"id": "ch03_react_plan", "no": 3, "title": "ReAct / Plan-and-Solve（LangGraph）", "group": GROUPS[1],
     "brief": "条件边闭环 vs PydanticOutputParser 结构化计划，对比灵活性与可审计性。",
     "fields": [{"key": "mode", "label": "策略", "type": "select", "default": "react",
                 "options": [{"value": "react", "label": "ReAct（走一步看一步）"},
                             {"value": "plan", "label": "Plan-and-Solve（先计划后执行）"}]},
                {"key": "task", "label": "任务", "type": "text", "default": "帮我给新员工陈明办理入职，并同步进度"}]},
    {"id": "ch04_workflow_hitl", "no": 4, "title": "StateGraph / interrupt / 人工审批", "group": GROUPS[1],
     "brief": "入职状态图 + interrupt 挂起 + Command(resume) 从 checkpoint 断点续跑。",
     "fields": [{"key": "candidate", "label": "候选人", "type": "text", "default": "陈明"},
                {"key": "case_id", "label": "已有 case_id（恢复用，可留空）", "type": "text", "default": ""}]},
    {"id": "ch05_memory", "no": 5, "title": "Memory（InMemoryStore + checkpointer）", "group": GROUPS[2],
     "brief": "会话记忆走 checkpointer，长期/用户记忆走 Store，重要性阈值过滤与隔离。",
     "fields": [{"key": "question", "label": "用户问题", "type": "text", "default": "帮我安排一场候选人面试，有什么需要注意的？"},
                {"key": "importance_threshold", "label": "重要性阈值", "type": "number", "default": 0.3}]},
    {"id": "ch06_context", "no": 6, "title": "Context Engineering（trim_messages）", "group": GROUPS[2],
     "brief": "trim_messages 滚动窗口 + 摘要链 + P0/P1/P2 预算装配，全部是 LCEL Runnable。",
     "fields": [{"key": "token_budget", "label": "Token 预算", "type": "number", "default": 500},
                {"key": "history_turns", "label": "历史轮数", "type": "number", "default": 12},
                {"key": "keep_recent", "label": "保留最近轮数", "type": "number", "default": 2}]},
    {"id": "ch07_rag_basic", "no": 7, "title": "RAG 基础（Document / VectorStore / LCEL）", "group": GROUPS[2],
     "brief": "Document → InMemoryVectorStore.as_retriever → RunnableLambda Rerank → 带引用生成链。",
     "fields": [{"key": "question", "label": "制度问题", "type": "text", "default": "公司有几天婚假？"},
                {"key": "top_k", "label": "召回条数", "type": "number", "default": 3}]},
    {"id": "ch08_rag_advanced", "no": 8, "title": "混合检索 / 版本治理（BaseRetriever）", "group": GROUPS[2],
     "brief": "自定义 BaseRetriever 三路 RRF 融合；active 软删除实现增量发布与撤销。",
     "fields": [{"key": "action", "label": "操作", "type": "select", "default": "search",
                 "options": [{"value": "search", "label": "混合检索"},
                             {"value": "publish", "label": "发布新制度 V2.4"},
                             {"value": "rollback", "label": "撤销回 V2.3"}]},
                {"key": "question", "label": "制度问题", "type": "text", "default": "婚假有多少天，需要什么材料？"}]},
    {"id": "ch09_graph_text2sql", "no": 9, "title": "Text2SQL / 图谱 / Ontology", "group": GROUPS[2],
     "brief": "指标类走 @tool 只读 SQL 网关，关系类走图谱检索，Ontology 约束 + 实体溯源。",
     "fields": [{"key": "mode", "label": "模式", "type": "select", "default": "hybrid",
                 "options": [{"value": "hybrid", "label": "两路都跑"},
                             {"value": "text2sql", "label": "仅 Text2SQL"},
                             {"value": "graph", "label": "仅图谱检索"}]},
                {"key": "sql_question", "label": "统计问题", "type": "text", "default": "产品部上个月平均加班多久？"},
                {"key": "graph_question", "label": "关系问题", "type": "text", "default": "谁和张三在同一个项目，张三向谁汇报？"}]},
    {"id": "ch10_mcp_skill", "no": 10, "title": "MCP / Skill / Plugin", "group": GROUPS[3],
     "brief": "langchain-mcp-adapters 真实拉起 stdio MCP Server；Skill 渐进式披露。",
     "fields": [{"key": "question", "label": "用户问题", "type": "text", "default": "我今年还剩几天年假？"}]},
    {"id": "ch11_multiagent", "no": 11, "title": "Multi-Agent（LangGraph supervisor）", "group": GROUPS[3],
     "brief": "4 个角色节点 + 共享黑板 TypedDict + 合规一票否决，仲裁写在代码里。",
     "fields": [{"key": "jd_id", "label": "JD 编号", "type": "select", "default": "J2001",
                 "options": [{"value": "J2001", "label": "J2001 高级后端工程师"},
                             {"value": "J2002", "label": "J2002 HRBP"}]}]},
    {"id": "ch12_sandbox_codemode", "no": 12, "title": "Sandbox / Code Mode / checkpoint 恢复", "group": GROUPS[3],
     "brief": "@tool 受限执行 + Harness 断言 + StateGraph checkpoint 断点续跑。",
     "fields": [{"key": "simulate_crash", "label": "模拟中途崩溃", "type": "select", "default": "false",
                 "options": [{"value": "false", "label": "否"}, {"value": "true", "label": "是（再用 case_id 恢复）"}]},
                {"key": "case_id", "label": "case_id（恢复用，可留空）", "type": "text", "default": ""}]},
    {"id": "ch13_reliability", "no": 13, "title": "可靠性（with_retry / with_fallbacks）", "group": GROUPS[4],
     "brief": "Runnable 原生重试与降级 + 超时 / 熔断 / 幂等 / recursion_limit 终止条件。",
     "fields": [{"key": "scenario", "label": "场景", "type": "select", "default": "all",
                 "options": [{"value": "all", "label": "全部演示"},
                             {"value": "retry", "label": "重试"}, {"value": "idempotency", "label": "幂等"},
                             {"value": "timeout", "label": "超时"}, {"value": "circuit_breaker", "label": "熔断"},
                             {"value": "degrade", "label": "降级"}, {"value": "termination", "label": "终止条件"}]}]},
    {"id": "ch14_eval", "no": 14, "title": "Trace / Metrics / 评测回归", "group": GROUPS[4],
     "brief": "BaseCallbackHandler 采集框架事件，Golden Case 回归 + Bad Case + Replay。",
     "fields": [{"key": "limit", "label": "Case 数量", "type": "number", "default": 5}]},
    {"id": "ch15_model_engineering", "no": 15, "title": "模型路由与结构化输出", "group": GROUPS[4],
     "brief": "RunnableLambda 路由不同 ChatOllama + PydanticOutputParser 校验修复，成本降 55%。",
     "fields": [{"key": "note", "label": "说明", "type": "text", "default": "本 Demo 固定演示 4 类任务"}]},
    {"id": "ch16_langchain_fullchain", "no": 16, "title": "LangGraph 全链路综合", "group": GROUPS[5],
     "brief": "把 15 章串成一张图：路由 → 上下文 → 工具循环 / RAG / 状态机审批 → 引用回答 → 记忆 → Trace。",
     "fields": [{"key": "scenario", "label": "场景", "type": "select", "default": "leave",
                 "options": [{"value": "leave", "label": "年假查询（工具循环）"},
                             {"value": "policy", "label": "婚假制度（RAG）"},
                             {"value": "termination", "label": "试用期辞退（RAG）"},
                             {"value": "sql", "label": "平均加班（Text2SQL）"},
                             {"value": "graph", "label": "组织关系（图谱）"},
                             {"value": "onboarding", "label": "办理入职（状态机 + 人工审批）"},
                             {"value": "mcp", "label": "MCP 工具调用"},
                             {"value": "chat", "label": "通用问答"},
                             {"value": "eval", "label": "端到端 Golden Case 回归"}]},
                {"key": "use_mcp", "label": "启用 MCP 适配器", "type": "select", "default": "false",
                 "options": [{"value": "false", "label": "否"}, {"value": "true", "label": "是"}]},
                {"key": "token_budget", "label": "Token 预算", "type": "number", "default": 3000},
                {"key": "max_steps", "label": "最大步数", "type": "number", "default": 6},
                {"key": "thread_id", "label": "thread_id（恢复用，可留空）", "type": "text", "default": ""}]},
]

ID_SET = {c["id"] for c in CHAPTER_META}


def _load(chapter_id: str):
    try:
        return importlib.import_module(f"demos.{chapter_id}.demo")
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"未找到章节模块 {chapter_id}：{exc}") from exc


def _clean(payload: dict) -> dict:
    """把前端字符串表单值转成 Demo 需要的类型，空字符串不传。"""
    out: dict = {}
    for k, v in (payload or {}).items():
        if v is None or v == "":
            continue
        if isinstance(v, str) and v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        elif isinstance(v, str) and v.lstrip("-").replace(".", "", 1).isdigit():
            out[k] = float(v) if "." in v else int(v)
        else:
            out[k] = v
    return out


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "mock" if (config.FORCE_MOCK or not ollama_client.is_available()) else "ollama",
            "models": ollama_client.list_models(), "chapters": len(CHAPTER_META),
            "model": config.OLLAMA_MODEL, "embed_model": config.OLLAMA_EMBED_MODEL,
            "framework": "LangChain / LangGraph"}


@app.get("/api/chapters")
def chapters() -> dict:
    return {"groups": GROUPS, "chapters": CHAPTER_META}


@app.post("/api/demo/{chapter_id}")
def run_demo(chapter_id: str, req: DemoRequest) -> JSONResponse:
    if chapter_id not in ID_SET:
        raise HTTPException(status_code=404, detail=f"未知章节 {chapter_id}")
    mod = _load(chapter_id)
    try:
        result = mod.run(_clean(req.payload))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{chapter_id} 执行失败：{type(exc).__name__}: {exc}") from exc
    return JSONResponse(result)


@app.post("/api/hitl/approve")
def approve(req: ApproveRequest) -> JSONResponse:
    """人工审批：ch04 与 ch16 都走 LangGraph interrupt + Command(resume)。

    ch16 的 hitl.case_id 就是 thread_id（lc- 前缀），据此路由到全链路恢复。
    """
    try:
        if req.case_id.startswith("lc-"):
            mod = _load("ch16_langchain_fullchain")
            result = mod.resume({"thread_id": req.case_id, "action": req.action,
                                 "approver": req.approver})
        else:
            mod = _load("ch04_workflow_hitl")
            result = mod.resume(req.case_id, req.action, req.approver)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/fullchain/state/{thread_id}")
def fullchain_state(thread_id: str) -> dict:
    """查看 LangGraph checkpointer 里某条全链路的挂起状态。"""
    mod = _load("ch16_langchain_fullchain")
    return mod.state(thread_id)


@app.get("/api/state/{case_id}")
def state(case_id: str) -> dict:
    return {"case": hr_data.get_case(case_id), "checkpoints": hr_data.load_checkpoints(case_id)}


@app.get("/api/audit")
def audit(limit: int = 20) -> dict:
    conn = hr_data.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    return {"items": rows}


@app.get("/")
def root() -> dict:
    return {"message": "HR Agent 教学控制台 API · LangChain / LangGraph 版", "docs": "/docs",
            "frontend": "cd frontend && npm install && npm run dev",
            "chapters_api": "/api/chapters", "tutorial": "docs/HR_Agent_从零到生产.md"}
