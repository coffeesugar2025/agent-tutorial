"""第 11 章：结构化知识 —— Text2SQL、Text2Cypher、GraphRAG 的边界。

跑法：python ch11_text2sql/main.py

为什么 HR 场景必须有这一章：
  "技术中心现在有多少人？" 这类问题，向量库永远答不准 —— 它要的是**聚合计算**，
  不是语义相似。数字类问题必须走 SQL / 图查询，不能靠 RAG 猜。

LangChain 原语：
  · SQLDatabase —— 把库连起来，给模型看 schema
  · with_structured_output(Query) —— 让模型只输出 SQL，不输出解释
  · 三层护栏：只读、表白名单、dry-run + 审计
"""

import sqlite3, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from common import ai_tool, get_model, practice, section, star, title

# ============================================================
# 0) 准备一个库（离线用 sqlite，生产可换 MySQL/PG）
# ============================================================
DB_PATH = pathlib.Path(__file__).resolve().parent / "hr_demo.db"
if DB_PATH.exists():
    DB_PATH.unlink()
con = sqlite3.connect(DB_PATH)
con.executescript("""
CREATE TABLE emp (emp_id TEXT PRIMARY KEY, name TEXT, dept TEXT, city TEXT, level TEXT, status TEXT, hired_at TEXT);
CREATE TABLE leave_bal (emp_id TEXT, year INT, leave_type TEXT, days REAL);
INSERT INTO emp VALUES
  ('E1001','张伟','技术中心','苏州','P6','active','2021-03-01'),
  ('E1002','李娜','技术中心','苏州','P5','active','2022-07-15'),
  ('E1003','王强','技术中心','北京','P7','active','2019-05-20'),
  ('E1004','陈静','业务中心','苏州','P5','active','2023-02-10'),
  ('E1005','刘洋','业务中心','上海','P6','active','2020-11-01'),
  ('E1006','赵敏','技术中心','苏州','P4','left','2024-01-08');
INSERT INTO leave_bal VALUES
  ('E1001',2026,'年假',7.0),('E1002',2026,'年假',5.0),('E1003',2026,'年假',10.0);
""")
con.commit()

# ★ SQLDatabase：LangChain 的"库直连"原语，能自动把表结构读成文本喂给模型
db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH.as_posix()}", include_tables=["emp", "leave_bal"])
SCHEMA = db.get_table_info()
print("  从库自动读出的 schema（前 6 行）：")
for line in SCHEMA.splitlines()[:6]:
    print(f"    {line}")

title("案例 1：同一句话，向量检索 vs SQL，答案完全不同")

print("  问：技术中心现在有多少人？")
print("    · RAG 会给一段'技术中心负责…'的描述 —— 没有数字，无法回答")
print("    · SQL 会给 3（在职口径：status='active' 且 dept='技术中心'）")
star("判据很简单：问'多少个/多少天/排名/占比/趋势'→ 走 SQL；问'规定是什么/怎么走流程'→ 走 RAG")

# ============================================================
# 2) Text2SQL：契约先行
# ============================================================
section("案例 2：让模型只输出 SQL，且必须带口径说明")

class Query(BaseModel):
    sql: str = Field(description="一条只读 SQL，禁止 INSERT/UPDATE/DELETE")
    caliber: str = Field(description="口径说明：统计范围、过滤条件，一句话")
    tables: list[str] = Field(description="用到的表名")


T2S = ChatPromptTemplate.from_messages([
    ("system", "把问题翻译成一条只读 SQL。只允许 SELECT。"
               "口径必须写清楚（在职=status为active；在岗人数不含 left）。\n{schema}"),
    ("human", "{question}"),
])
sql_model = T2S | get_model([ai_tool("Query", {
    "sql": "SELECT COUNT(*) AS n FROM emp WHERE dept='技术中心' AND status='active'",
    "caliber": "统计技术中心在职（status=active）员工数，不含已离职",
    "tables": ["emp"],
}, "q1")]).with_structured_output(Query)

q = sql_model.invoke({"schema": SCHEMA, "question": "技术中心现在有多少人？"})
print(f"\n  SQL：{q.sql}\n  口径：{q.caliber}\n  用到的表：{q.tables}")

# ============================================================
# 3) 三层护栏：只读 / 表白名单 / 审计
# ============================================================
section("案例 3：把 SQL 执行做成'不可能出事'")

ALLOWED_TABLES = {"emp", "leave_bal"}
ALLOWED_PREFIX = ("SELECT", "WITH")


def guarded_exec(cur: sqlite3.Cursor, query: Query) -> list[tuple]:
    sql = query.sql.strip()
    if not sql.upper().startswith(ALLOWED_PREFIX):
        raise PermissionError("只允许 SELECT / WITH 开头的只读查询")
    for bad in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "ATTACH", "PRAGMA"):
        if bad in sql.upper():
            raise PermissionError(f"命中危险关键字：{bad}")
    if not set(query.tables) <= ALLOWED_TABLES:
        raise PermissionError(f"越权访问表：{set(query.tables) - ALLOWED_TABLES}")
    rows = cur.execute(sql).fetchall()
    audit.append({"sql": sql, "rows": len(rows), "caliber": query.caliber})
    return rows


audit: list[dict] = []
rows = guarded_exec(con.cursor(), q)
print(f"  执行结果：{rows[0][0]} 人")
print(f"  审计日志：{audit[-1]}")

# 攻击演示
class Evil(Query):
    pass


evil = Query(sql="DELETE FROM emp WHERE dept='技术中心'", caliber="清空数据", tables=["emp"])
try:
    guarded_exec(con.cursor(), evil)
except PermissionError as e:
    print(f"\n  恶意 SQL 被拦：{e}")
evil2 = Query(sql="SELECT * FROM salary_secret", caliber="看薪资", tables=["salary_secret"])
try:
    guarded_exec(con.cursor(), evil2)
except PermissionError as e:
    print(f"  越权表被拦：{e}")
star("Text2SQL 的安全不靠 prompt，靠'执行层'：只读、白名单、审计三件套，缺一个都不能上线")

# ============================================================
# 4) Text2Cypher / GraphRAG：什么时候需要图
# ============================================================
section("案例 4：什么时候该上知识图谱")

# 用 dict 模拟三元组（生产换 Neo4j + langchain-neo4j 的 Neo4jGraph）
triples = [
    ("E1001", "任职于", "技术中心"),
    ("E1001", "汇报给", "E1003"),
    ("E1003", "负责", "前端平台"),
    ("前端平台", "依赖", "设计系统"),
    ("C1024", "应聘", "P1001"),
    ("P1001", "属于", "前端平台"),
]

def neighbors(node: str, depth: int = 2) -> list[str]:
    """两跳邻居查询：'谁会影响前端平台的交付' 这种问题，SQL 要写 3 层 JOIN，图上一步就够。"""
    frontier, seen, path = {node}, {node}, []
    for _ in range(depth):
        nxt = set()
        for a, rel, b in triples:
            if a in frontier and b not in seen:
                nxt.add(b); path.append(f"{a} -{rel}-> {b}")
            if b in frontier and a not in seen:
                nxt.add(a); path.append(f"{b} <-{rel}- {a}")
        seen |= nxt; frontier = nxt
    return path


print("\n  '谁会影响前端平台的交付？' 从 前端平台 出发两跳：")
for p in neighbors("前端平台", 2)[:4]:
    print(f"    {p}")

for line in [
    "· 图的强项：多跳关系、影响面分析、组织架构、技能-岗位-项目三角",
    "· 图的成本：抽取三元组要人审（LLM 抽的关系一半是错的）、维护成本高",
    "· 经验：先把 SQL 做扎实，出现'要 3 跳以上才能答'的问题，再考虑图",
]:
    print(f"    {line}")

practice([
    "把 '各部门在职人数' 跑一遍，检查口径字段是否被模型写清",
    "给 guarded_exec 加 dry-run（EXPLAIN），先看代价再执行",
    "用 langchain-neo4j 的 Neo4jGraph 替换 triples，跑通 Text2Cypher",
])
