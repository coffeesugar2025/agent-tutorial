"""FastAPI 入口：API + 静态站点托管 + 启动命令。

启动（任意工作目录均可）：

    python app/backend/main.py

API 优先；若 ``app/frontend/dist`` 存在，则自动托管前端并对非 ``/api`` 路径
做 SPA fallback 到 ``index.html``。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

try:  # 作为包导入
    from . import config, evaluation
    from .agent import AgentInputError, HRAgent
    from .rag import KnowledgeBase
    from .store import Store
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]
    import evaluation  # type: ignore[no-redef]
    from agent import AgentInputError, HRAgent  # type: ignore[no-redef]
    from rag import KnowledgeBase  # type: ignore[no-redef]
    from store import Store  # type: ignore[no-redef]

from common.data import employee as find_employee, employees

# ---------------------------------------------------------------------------
# Pydantic 请求模型（字段全部给默认值，非法输入统一转成 400，而不是 FastAPI 422）
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = ""
    employee_id: str = ""
    idempotency_key: str | None = None


class ApprovalRequest(BaseModel):
    decision: str = ""
    comment: str | None = None
    approver: str = ""


# ---------------------------------------------------------------------------
# 运行时（可 reset，便于测试与演示）
# ---------------------------------------------------------------------------
_rag: KnowledgeBase | None = None
_runtime: "Runtime | None" = None


def get_rag() -> KnowledgeBase:
    global _rag
    if _rag is None:
        _rag = KnowledgeBase()
    return _rag


class Runtime:
    def __init__(self) -> None:
        self.store = Store()
        self.agent = HRAgent(self.store, get_rag())


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


def reset_state() -> None:
    """清空内存状态（测试 fixture / 演示重置用），知识库索引只读可复用。"""
    global _runtime
    _runtime = None


def reset_demo() -> dict:
    """重置演示数据到种子初始状态。

    清除：会话、审批单、请假申请、入职记录、薪资覆盖、审计链。
    保留：Golden Case 与只读制度索引（评测每次读取原始文件，不受影响）。
    """
    global _runtime
    previous = _runtime or get_runtime()
    previous.store.clear_persisted_state()
    _runtime = Runtime()
    return {"status": "ok", "reset_at": config.iso()}


app = FastAPI(
    title="HR Agent 智能服务台 API",
    version=config.VERSION,
    description="教程综合项目后端：制度检索、工具调用、审批、审计与评测。所有数据均为虚构。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 文档（课程章节）扫描
# ---------------------------------------------------------------------------
def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return inner
        return inner
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
    lowered = value.lower()
    if lowered in {"null", "~", "none"}:
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parse_frontmatter(raw: str) -> dict:
    """解析教程章节的极简 YAML frontmatter（只支持标量、引号字符串、行内数组）。"""
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            end_index = index
            break
    if end_index is None:
        return {}
    meta: dict[str, Any] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_scalar(value.strip())
    return meta


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _scan_docs() -> list[dict]:
    """扫描 docs/*.md，排除 ``_`` 开头的内部文件，按 part 分组。"""
    docs: list[dict] = []
    docs_dir = config.DOCS_DIR
    if not docs_dir.is_dir():
        return docs
    for path in sorted(docs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta = parse_frontmatter(raw)
        if not meta:
            continue
        prefix_match = re.match(r"^(\d+)-", path.stem)
        fallback_order = int(prefix_match.group(1)) if prefix_match else 999
        fallback_slug = re.sub(r"^\d+-", "", path.stem)

        order_raw = meta.get("order", fallback_order)
        try:
            order = int(order_raw)
        except (TypeError, ValueError):
            order = fallback_order
        minutes_raw = meta.get("minutes", 45)
        try:
            minutes = int(minutes_raw)
        except (TypeError, ValueError):
            minutes = 45
        prerequisites = meta.get("prerequisites") or []
        if isinstance(prerequisites, str):
            prerequisites = [prerequisites] if prerequisites else []

        part_title = str(meta.get("part") or config.FALLBACK_PART_TITLE).strip()
        docs.append(
            {
                "slug": str(meta.get("slug") or fallback_slug).strip(),
                "title": str(meta.get("title") or _first_heading(raw) or fallback_slug).strip(),
                "markdown": raw,
                "order": order,
                "minutes": minutes,
                "difficulty": str(meta.get("difficulty") or "入门").strip(),
                "summary": str(meta.get("summary") or "").strip(),
                "part_title": part_title,
                "part_id": config.PART_ID_BY_TITLE.get(part_title, config.FALLBACK_PART_ID),
                "prerequisites": prerequisites,
                "path": path.name,
            }
        )
    docs.sort(key=lambda item: (item["order"], item["slug"]))
    return docs


def build_course() -> dict:
    docs = _scan_docs()
    grouped: dict[str, list[dict]] = {}
    for doc in docs:
        grouped.setdefault(doc["part_id"], []).append(
            {
                "slug": doc["slug"],
                "title": doc["title"],
                "order": doc["order"],
                "minutes": doc["minutes"],
                "difficulty": doc["difficulty"],
                "summary": doc["summary"],
            }
        )
    parts: list[dict] = []
    for part_id, part_title in config.PARTS:
        chapters = grouped.get(part_id, [])
        if chapters:
            parts.append({"id": part_id, "title": part_title, "chapters": chapters})
    fallback = grouped.get(config.FALLBACK_PART_ID)
    if fallback:
        parts.append(
            {"id": config.FALLBACK_PART_ID, "title": config.FALLBACK_PART_TITLE, "chapters": fallback}
        )
    return {"title": config.COURSE_TITLE, "parts": parts}


# ---------------------------------------------------------------------------
# 快捷场景（8 个）
# ---------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {
        "id": "leave-balance",
        "label": "查年假余额",
        "message": "我还有几天年假？",
        "employee_id": "E1001",
        "risk": "low",
    },
    {
        "id": "leave-carryover",
        "label": "年假结转规则",
        "message": "年假没休完可以结转到什么时候？",
        "employee_id": "E1001",
        "risk": "low",
    },
    {
        "id": "leave-apply",
        "label": "提交 3 天年假申请",
        "message": "帮我提交 2026-12-01 到 2026-12-03 的 3 天年假申请",
        "employee_id": "E1001",
        "risk": "medium",
    },
    {
        "id": "candidate-vue",
        "label": "找 Vue3 前端候选人",
        "message": "帮我找会 Vue3 的前端候选人",
        "employee_id": "E1010",
        "risk": "low",
    },
    {
        "id": "interview-wanghao",
        "label": "安排王浩面试（需审批）",
        "message": "安排王浩 2026-12-05 14:00 面试",
        "employee_id": "E1010",
        "risk": "high",
    },
    {
        "id": "salary-zhangwei",
        "label": "把张伟薪资调到 P6-1（需审批）",
        "message": "把张伟的薪资调整到 P6-1",
        "employee_id": "E1004",
        "risk": "high",
    },
    {
        "id": "remote-2027-draft",
        "label": "2027 远程办公讨论稿是否生效",
        "message": "2027 远程办公讨论稿是否生效？",
        "employee_id": "E1001",
        "risk": "low",
    },
    {
        "id": "out-of-scope-weather",
        "label": "边界问题转人工",
        "message": "今天天气怎么样？",
        "employee_id": "E1001",
        "risk": "low",
    },
]


# ---------------------------------------------------------------------------
# 课程 / 文档接口
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    runtime = get_runtime()
    return {
        "status": "ok",
        "version": config.VERSION,
        "llm_mode": config.LLM_MODE,
        "chapters": config.CHAPTER_COUNT,
        "kb_chunks": get_rag().chunk_count,
    }


@app.get("/api/course")
def course() -> dict:
    return build_course()


@app.get("/api/docs/{slug}")
def docs_detail(slug: str) -> dict:
    target = next((item for item in _scan_docs() if item["slug"] == slug), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"未找到章节：{slug}")
    return {
        "slug": target["slug"],
        "title": target["title"],
        "markdown": target["markdown"],
        "meta": {
            "order": target["order"],
            "minutes": target["minutes"],
            "difficulty": target["difficulty"],
            "part": target["part_title"],
            "prerequisites": target["prerequisites"],
            "summary": target["summary"],
        },
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [dict(item) for item in SCENARIOS]


# ---------------------------------------------------------------------------
# 知识库
# ---------------------------------------------------------------------------
@app.get("/api/kb/search")
def kb_search(
    q: str = Query(default=""),
    top_k: int = Query(default=5),
    include_archived: bool = Query(default=False),
    include_drafts: bool = Query(default=False),
) -> dict:
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询词 q 不能为空")
    if top_k < 1 or top_k > 20:
        raise HTTPException(status_code=400, detail="top_k 必须在 1 到 20 之间")
    results = get_rag().search(
        query,
        top_k=top_k,
        include_archived=include_archived,
        include_drafts=include_drafts,
        today=get_runtime().store.now().date(),
    )
    return {
        "query": query,
        "results": [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in results
        ],
    }


# ---------------------------------------------------------------------------
# 对话
# ---------------------------------------------------------------------------
@app.post("/api/chat")
def chat(request: Request, body: ChatRequest) -> dict:
    runtime = get_runtime()
    message = (body.message or "").strip()
    employee_id = (body.employee_id or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if not employee_id:
        raise HTTPException(status_code=400, detail="缺少演示身份 employee_id")
    idempotency_key = (
        body.idempotency_key
        or request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
    )
    session_id = (body.session_id or "").strip() or None
    try:
        result = runtime.agent.run(
            message,
            employee_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
    except AgentInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.payload


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    payload = get_runtime().store.session_payload(session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return payload


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------
@app.post("/api/approvals/{approval_id}")
def decide_approval(approval_id: str, body: ApprovalRequest) -> dict:
    runtime = get_runtime()
    store = runtime.store
    approval = store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail=f"审批单不存在：{approval_id}")
    if approval.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"审批单已处理（当前状态：{approval.get('status')}），不能重复审批",
        )

    decision = (body.decision or "").strip().lower()
    if decision in {"approve", "approved", "同意", "通过"}:
        decision = "approve"
    elif decision in {"reject", "rejected", "拒绝", "驳回"}:
        decision = "reject"
    else:
        raise HTTPException(status_code=400, detail="decision 只能是 approve 或 reject")

    approver = (body.approver or "").strip()
    if not approver:
        raise HTTPException(status_code=400, detail="缺少审批人 approver")
    approver_person = find_employee(approver) or next(
        (item for item in employees() if item["name"] == approver), None
    )
    if approver_person is None:
        raise HTTPException(status_code=400, detail=f"审批人不存在：{approver}")
    approver = approver_person["id"]
    if approver not in config.HR_ROLES:
        raise HTTPException(
            status_code=400, detail="审批人没有权限：仅 HR 角色可以审批"
        )

    decided = store.decide_approval(
        approval_id, decision, approver, (body.comment or "").strip() or None
    )
    if decided is None:  # pragma: no cover - 上面的 404 已覆盖
        raise HTTPException(status_code=404, detail=f"审批单不存在：{approval_id}")
    if decided["status"] == "rejected":
        result_text = f"已拒绝该申请（{decided['summary']}），未执行任何变更。"
        audit = store.record_audit(
            approver, "reject_approval", approval_id, result_text
        )
        session = store.get_session(decided.get("session_id") or "")
        if session is not None:
            store.add_fact(session, f"已拒绝审批：{decided['action']}（{approval_id}）")
        return {
            "approval_id": approval_id,
            "status": "rejected",
            "session_id": decided.get("session_id"),
            "result": result_text,
            "audit_id": audit["id"],
        }

    store.record_audit(approver, "approve_approval", approval_id, decided["summary"])
    try:
        result_text, audit = runtime.agent.toolbox.execute_approval(decided, approver)
    except Exception as exc:  # noqa: BLE001 - 执行失败要回写状态并留审计
        failed_text = f"审批已通过，但执行失败：{exc}"
        store.set_approval_status(approval_id, "failed", failed_text)
        failed_audit = store.record_audit(
            approver, "execute_failed", approval_id, failed_text
        )
        return {
            "approval_id": approval_id,
            "status": "failed",
            "session_id": decided.get("session_id"),
            "result": failed_text,
            "audit_id": failed_audit["id"],
        }
    session = store.get_session(decided.get("session_id") or "")
    if session is not None:
        store.add_fact(session, f"审批通过并已执行：{decided['action']}（{approval_id}）")
    return {
        "approval_id": approval_id,
        "status": "approved",
        "session_id": decided.get("session_id"),
        "result": result_text,
        "audit_id": audit["id"],
    }


# ---------------------------------------------------------------------------
# 评测
# ---------------------------------------------------------------------------
@app.post("/api/eval/run")
def run_eval() -> dict:
    return evaluation.run_evaluation(get_rag())


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    """把演示数据恢复到种子状态，便于反复演示审批与写操作。"""
    return reset_demo()


# ---------------------------------------------------------------------------
# 审计（教程额外暴露的只读调试接口，方便课堂演示哈希链）
# ---------------------------------------------------------------------------
@app.get("/api/audit")
def audit_log() -> dict:
    store = get_runtime().store
    events = store.audit_events()
    return {"count": len(events), "valid": store.verify_audit_chain(), "events": events}


# ---------------------------------------------------------------------------
# 统一错误格式
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": "请求参数不合法，请检查字段类型与必填项"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if detail in {None, "Not Found"}:
        detail = "接口不存在"
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


# ---------------------------------------------------------------------------
# 静态站点：API 优先，其余走 SPA fallback
# ---------------------------------------------------------------------------
def _safe_dist_file(relative_path: str) -> Path | None:
    dist = config.FRONTEND_DIST
    if not dist.is_dir():
        return None
    try:
        candidate = (dist / relative_path).resolve()
        candidate.relative_to(dist.resolve())
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


if (config.FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(config.FRONTEND_DIST / "assets")),
        name="assets",
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")
    if full_path:
        static_file = _safe_dist_file(full_path)
        if static_file is not None:
            return FileResponse(static_file)
    index_file = config.FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(
        status_code=404,
        detail=(
            "前端尚未构建：请先执行 cd app/frontend; pnpm install; pnpm build，"
            "或使用 pnpm dev 在 5173 端口开发。"
        ),
    )


def main() -> None:
    import uvicorn

    host = os.getenv("HR_APP_HOST", "127.0.0.1")
    port = int(os.getenv("HR_APP_PORT", "8000"))
    dist_ready = (config.FRONTEND_DIST / "index.html").is_file()
    print("=" * 60)
    print(f"  {config.APP_NAME}  v{config.VERSION}")
    print(f"  API:      http://{host}:{port}/api/health")
    print(f"  Swagger:  http://{host}:{port}/docs")
    print(f"  前端:     {'已托管 app/frontend/dist' if dist_ready else 'dist 不存在，仅提供 API'}")
    print(f"  知识库:   {get_rag().chunk_count} 个片段")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
