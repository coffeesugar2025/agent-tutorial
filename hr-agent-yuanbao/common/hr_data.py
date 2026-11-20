"""假 HR 业务系统：SQLite + 内存常量，用来代替真实 HCM / OA / 考勤系统。

教程反复强调的一句话：**Agent 的价值不在聊天，在于能接系统、改状态、留痕迹**。
所以这里刻意做了真实系统该有的东西：主键、状态字段、幂等键、审计日志、只读 SQL 白名单。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from . import config

# ---------------- 内存业务数据（简历 / JD / 组织关系） ----------------

EMPLOYEES = [
    ("E1001", "张三", "产品部", "产品经理", "E1002", "2023-03-01", 5.5, "在职"),
    ("E1002", "李四", "产品部", "产品总监", "E1000", "2020-07-15", 12.0, "在职"),
    ("E1003", "王五", "研发部", "后端工程师", "E1005", "2024-01-08", 3.0, "在职"),
    ("E1004", "赵六", "财务部", "会计", "E1002", "2022-11-20", 8.0, "在职"),
    ("E1005", "孙七", "研发部", "研发经理", "E1000", "2019-05-06", 15.0, "在职"),
    ("E1000", "周总", "总经办", "总经理", None, "2018-01-01", 20.0, "在职"),
]

ATTENDANCE = [
    ("E1001", "2026-10", 168.0, 12.5),
    ("E1002", "2026-10", 172.0, 6.0),
    ("E1003", "2026-10", 176.0, 22.0),
    ("E1004", "2026-10", 168.0, 3.0),
    ("E1005", "2026-10", 170.0, 10.0),
]

JDS = {
    "J2001": {
        "title": "高级后端工程师", "dept": "研发部",
        "must": ["Python", "FastAPI", "分布式", "5 年以上"],
        "nice": ["Agent/RAG 经验", "MySQL 调优", "K8s"],
    },
    "J2002": {
        "title": "HRBP", "dept": "人力资源部",
        "must": ["员工关系", "3 年以上", "劳动法"],
        "nice": ["HCM 系统", "数据分析"],
    },
}

CANDIDATES = [
    {"id": "C01", "name": "陈明", "years": 7, "skills": ["Python", "FastAPI", "分布式", "MySQL 调优"], "expect": "高级后端工程师", "risk": "无"},
    {"id": "C02", "name": "林晓", "years": 3, "skills": ["Python", "Django", "RAG 经验"], "expect": "高级后端工程师", "risk": "年限不足"},
    {"id": "C03", "name": "吴芳", "years": 6, "skills": ["员工关系", "劳动法", "HCM 系统"], "expect": "HRBP", "risk": "无"},
]

# 组织知识图谱：(起点, 关系, 终点)。第 9 章 GraphRAG / Text2Cypher 用
ORG_EDGES = [
    ("张三", "汇报给", "李四"), ("王五", "汇报给", "孙七"),
    ("赵六", "汇报给", "李四"), ("李四", "汇报给", "周总"), ("孙七", "汇报给", "周总"),
    ("张三", "属于", "产品部"), ("李四", "属于", "产品部"),
    ("王五", "属于", "研发部"), ("孙七", "属于", "研发部"), ("赵六", "属于", "财务部"),
    ("张三", "参与项目", "HR 智能助手"), ("王五", "参与项目", "HR 智能助手"),
    ("孙七", "参与项目", "HR 智能助手"), ("李四", "参与项目", "供应链 Control Tower"),
    ("张三", "掌握技能", "需求分析"), ("王五", "掌握技能", "Python"),
    ("孙七", "掌握技能", "架构设计"), ("HR 智能助手", "归属领域", "企业内部效率"),
]

DDL = """
CREATE TABLE IF NOT EXISTS employees(
  emp_id TEXT PRIMARY KEY, name TEXT, dept TEXT, title TEXT,
  manager_id TEXT, hire_date TEXT, leave_balance REAL, status TEXT);
CREATE TABLE IF NOT EXISTS attendance(
  emp_id TEXT, month TEXT, hours REAL, overtime REAL,
  PRIMARY KEY(emp_id, month));
CREATE TABLE IF NOT EXISTS leave_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT, start_date TEXT, end_date TEXT,
  days REAL, reason TEXT, status TEXT, idem_key TEXT UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS onboarding_cases(
  case_id TEXT PRIMARY KEY, candidate TEXT, dept TEXT, position TEXT,
  status TEXT, node TEXT, payload TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT,
  target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS memory(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, scope TEXT,
  key TEXT, value TEXT, importance REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS kb_docs(
  doc_id TEXT PRIMARY KEY, title TEXT, version TEXT, content_hash TEXT,
  active INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS kb_chunks(
  chunk_id TEXT PRIMARY KEY, doc_id TEXT, version TEXT, seq INTEGER,
  text TEXT, active INTEGER);
CREATE TABLE IF NOT EXISTS eval_cases(
  case_id TEXT PRIMARY KEY, question TEXT, expect_tool TEXT,
  expect_keywords TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS eval_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, case_id TEXT,
  passed INTEGER, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(
  case_id TEXT, node TEXT, payload TEXT, updated_at TEXT,
  PRIMARY KEY(case_id, node));
"""

_initialized = False
_use_memory = False
_keeper: sqlite3.Connection | None = None   # 共享内存库需要一个长连接保活

_GOLDEN = [
    ("G01", "我今年还剩几天年假？", "get_leave_balance", "年假,5.5", "工具调用"),
    ("G02", "试用期辞退员工要走什么流程？", "search_handbook", "试用期,流程", "RAG"),
    ("G03", "帮我给新员工办理入职", "create_onboarding", "审批,入职", "状态机"),
    ("G04", "产品部上个月平均加班多久？", "text2sql", "加班,平均", "Text2SQL"),
    ("G05", "公司有几天婚假？", "search_handbook", "婚假", "RAG"),
]


def _raw() -> sqlite3.Connection:
    """正常环境用文件库（可持久化 checkpoint / 版本 / 审计）；
    某些受限文件系统不支持 SQLite 文件锁时，自动降级为共享内存库，
    保证教学 Demo 在任何环境都能跑通（进程内数据一致）。"""
    if _use_memory:
        conn = sqlite3.connect("file:hr_agent_course_mem?mode=memory&cache=shared",
                               uri=True, timeout=10)
    else:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.executemany("INSERT OR IGNORE INTO employees VALUES(?,?,?,?,?,?,?,?)", EMPLOYEES)
    conn.executemany("INSERT OR IGNORE INTO attendance VALUES(?,?,?,?)", ATTENDANCE)
    conn.executemany("INSERT OR IGNORE INTO eval_cases VALUES(?,?,?,?,?)", _GOLDEN)
    conn.commit()


def init_db() -> None:
    global _initialized, _use_memory, _keeper
    if _initialized:
        return
    try:
        conn = _raw()
        try:
            _seed(conn)
        finally:
            conn.close()
    except sqlite3.OperationalError:
        _use_memory = True
        _keeper = _raw()          # 保活，避免共享内存库被 GC 掉
        conn = _raw()
        try:
            _seed(conn)
        finally:
            conn.close()
    _initialized = True


def connect() -> sqlite3.Connection:
    init_db()
    return _raw()


def storage_mode() -> str:
    init_db()
    return "shared-memory（受限文件系统降级）" if _use_memory else f"file:{config.DB_PATH.name}"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 供 Agent 调用的业务工具 ----------------

def get_employee(name_or_id: str) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM employees WHERE emp_id=? OR name=?", (name_or_id, name_or_id)
        ).fetchone()
        return dict(row) if row else {"error": f"未找到员工 {name_or_id}"}
    finally:
        conn.close()


def get_leave_balance(emp_id: str, year: int = 2026) -> dict:
    row = get_employee(emp_id)
    if "error" in row:
        return row
    return {
        "emp_id": emp_id, "name": row["name"], "year": year,
        "leave_balance": row["leave_balance"], "unit": "天",
        "source": "HCM.leave_account", "as_of": now(),
    }


def get_attendance(emp_id: str, month: str = "2026-10") -> dict:
    conn = connect()
    try:
        r = conn.execute(
            "SELECT * FROM attendance WHERE emp_id=? AND month=?", (emp_id, month)
        ).fetchone()
        return dict(r) if r else {"error": "无该月考勤数据"}
    finally:
        conn.close()


def submit_leave(emp_id: str, start_date: str, end_date: str, days: float,
                 reason: str, idem_key: str) -> dict:
    """幂等写入：同一 idem_key 重复提交只返回第一次结果，绝不产生两条单据。"""
    conn = connect()
    try:
        old = conn.execute("SELECT * FROM leave_requests WHERE idem_key=?", (idem_key,)).fetchone()
        if old:
            return {"status": "duplicate_ignored", "request_id": old["id"], "message": "重复请求已幂等忽略"}
        cur = conn.execute(
            "INSERT INTO leave_requests(emp_id,start_date,end_date,days,reason,status,idem_key,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (emp_id, start_date, end_date, days, reason, "待主管审批", idem_key, now()),
        )
        conn.commit()
        return {"status": "created", "request_id": cur.lastrowid, "next": "待主管审批"}
    finally:
        conn.close()


def create_onboarding(candidate: str, dept: str, position: str) -> dict:
    case_id = "ONB-" + uuid.uuid4().hex[:8].upper()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO onboarding_cases VALUES(?,?,?,?,?,?,?,?)",
            (case_id, candidate, dept, position, "WAIT_MANAGER_APPROVE", "collect_material",
             json.dumps({"candidate": candidate, "dept": dept}, ensure_ascii=False), now()),
        )
        conn.commit()
    finally:
        conn.close()
    audit("agent", "create_onboarding", case_id, f"{candidate} / {dept} / {position}")
    return {"case_id": case_id, "status": "WAIT_MANAGER_APPROVE", "node": "collect_material"}


def get_case(case_id: str) -> dict:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM onboarding_cases WHERE case_id=?", (case_id,)).fetchone()
        return dict(r) if r else {"error": "case 不存在"}
    finally:
        conn.close()


def update_case(case_id: str, status: str, node: str, payload: dict | None = None) -> None:
    conn = connect()
    try:
        old = conn.execute("SELECT payload FROM onboarding_cases WHERE case_id=?", (case_id,)).fetchone()
        merged = json.loads(old["payload"]) if old and old["payload"] else {}
        merged.update(payload or {})
        conn.execute(
            "UPDATE onboarding_cases SET status=?, node=?, payload=?, updated_at=? WHERE case_id=?",
            (status, node, json.dumps(merged, ensure_ascii=False), now(), case_id),
        )
        conn.commit()
    finally:
        conn.close()
    audit("workflow", f"state -> {status}", case_id, node)


def checkpoint(case_id: str, node: str, payload: dict) -> None:
    """长任务恢复：每完成一个节点就落一次 checkpoint，崩溃后从这里续跑。"""
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)",
            (case_id, node, json.dumps(payload, ensure_ascii=False), now()),
        )
        conn.commit()
    finally:
        conn.close()


def load_checkpoints(case_id: str) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT node, payload, updated_at FROM checkpoints WHERE case_id=? ORDER BY updated_at", (case_id,)
        )]
    finally:
        conn.close()


def audit(actor: str, action: str, target: str, detail: str = "") -> None:
    conn = connect()
    try:
        conn.execute("INSERT INTO audit_log(ts,actor,action,target,detail) VALUES(?,?,?,?,?)",
                     (now(), actor, action, target, detail))
        conn.commit()
    finally:
        conn.close()


def memory_put(user_id: str, scope: str, key: str, value: str, importance: float = 0.5) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO memory(user_id,scope,key,value,importance,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, scope, key, value, importance, now()),
        )
        conn.commit()
    finally:
        conn.close()


def memory_get(user_id: str, limit: int = 20) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM memory WHERE user_id=? ORDER BY importance DESC, id DESC LIMIT ?",
            (user_id, limit),
        )]
    finally:
        conn.close()


def readonly_sql(sql: str) -> dict:
    """Text2SQL 的最小安全边界：只允许单条 SELECT，禁止写操作与敏感关键字。"""
    s = sql.strip().rstrip(";")
    banned = ("insert", "update", "delete", "drop", "alter", "attach", "pragma", "create", "--", "/*")
    if not s.lower().startswith("select") or any(b in s.lower() for b in banned):
        return {"error": "SQL 未通过白名单校验（只允许单条只读 SELECT）", "sql": sql}
    conn = connect()
    try:
        rows = conn.execute(s).fetchall()
        return {"columns": list(rows[0].keys()) if rows else [], "rows": [dict(r) for r in rows], "rowcount": len(rows)}
    except Exception as exc:
        return {"error": f"SQL 执行失败：{exc}", "sql": sql}
    finally:
        conn.close()


def load_handbook() -> list[dict]:
    """读取 data/handbook 下的制度文档，作为 RAG 语料。"""
    out = []
    for p in sorted(Path(config.HANDBOOK_DIR).glob("*.md")):
        out.append({"doc_id": p.stem, "title": p.stem, "path": str(p), "text": p.read_text(encoding="utf-8")})
    return out
