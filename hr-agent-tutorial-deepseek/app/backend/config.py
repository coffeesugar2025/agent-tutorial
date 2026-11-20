"""全局路径与常量。

所有路径都基于 ``__file__`` 解析，因此无论从仓库根目录、``app/backend``
还是其他任意工作目录启动，都能找到 ``docs/``、``code/data`` 和前端构建产物。

同时把 ``code/`` 加入 ``sys.path``，复用教程前 15 章沉淀下来的
``common.data / common.text / common.trace``，避免重复造轮子。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
PROJECT_ROOT = APP_DIR.parent

CODE_DIR = PROJECT_ROOT / "code"
DATA_DIR = CODE_DIR / "data"
POLICY_DIR = DATA_DIR / "policies"
DOCS_DIR = PROJECT_ROOT / "docs"
FRONTEND_DIR = APP_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
GOLDEN_CASES_PATH = DATA_DIR / "golden_cases.jsonl"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# ---------------------------------------------------------------------------
# 应用元信息
# ---------------------------------------------------------------------------
APP_NAME = "HR Agent 智能服务台"
COURSE_TITLE = "HR Agent 实战教程"
VERSION = "1.0.0"
LLM_MODE = os.getenv("HR_LLM_MODE", "mock").lower()
CHAPTER_COUNT = 18  # 教程固定 18 章（00–17），/api/health 的课程元数据
SESSION_MAX_MESSAGES = 20
MEMORY_MAX_FACTS = 8
MAX_MESSAGE_CHARS = 2000

# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------
TZ = timezone(timedelta(hours=8))

# 评测固定时钟：让 20 条 Golden Case 的“是否提前 3 个工作日”等判断
# 在任何机器、任何日期都得到相同结果（教程强调评测可复现）。
REFERENCE_NOW = datetime(2026, 11, 15, 10, 0, 0, tzinfo=TZ)


def now() -> datetime:
    """线上请求使用的当前时间（东八区）。"""
    return datetime.now(TZ)


def iso(moment: datetime | None = None) -> str:
    """ISO 8601，带时区，精确到秒。"""
    return (moment or now()).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 课程结构：五个固定 part
# ---------------------------------------------------------------------------
PARTS: list[tuple[str, str]] = [
    ("part-0", "启程：从 HR 痛点理解 Agent"),
    ("part-1", "单 Agent 核心"),
    ("part-2", "RAG 与知识工程"),
    ("part-3", "生产级可靠性"),
    ("part-4", "项目实战与求职"),
]
PART_ID_BY_TITLE = {title: part_id for part_id, title in PARTS}
PART_TITLE_BY_ID = {part_id: title for part_id, title in PARTS}
FALLBACK_PART_ID = "part-9"
FALLBACK_PART_TITLE = "其他"

# ---------------------------------------------------------------------------
# 权限（演示用 RBAC：生产环境应替换成 OIDC / JWT + 组织角色）
# ---------------------------------------------------------------------------
HR_ROLES = frozenset({"E1004", "E2004", "E1010"})  # HRBP / HR 总监 / 招聘专员
SALARY_APPROVERS = frozenset({"E1004", "E2004"})  # 调薪审批：HRBP / HR 总监
RECRUITMENT_ROLES = frozenset({"E1004", "E2004", "E1010"})

# ---------------------------------------------------------------------------
# 成本估算（USD / 1M tokens；仅演示，真实计费以厂商账单为准）
# ---------------------------------------------------------------------------
PRICE_PROMPT_PER_M = 0.15
PRICE_COMPLETION_PER_M = 0.60

# ---------------------------------------------------------------------------
# HTTP / CORS
# ---------------------------------------------------------------------------
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """按估算 token 折算美元成本，保留 6 位小数。"""
    cost = (
        prompt_tokens * PRICE_PROMPT_PER_M + completion_tokens * PRICE_COMPLETION_PER_M
    ) / 1_000_000
    return round(cost, 6)
