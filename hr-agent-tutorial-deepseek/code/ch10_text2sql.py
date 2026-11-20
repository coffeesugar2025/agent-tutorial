"""第 10 章：知识图谱与 Text2SQL（LangChain 版）。

向量检索擅长「找一段话」，但回答不了「技术部谁有 RAG 经验」「各部门平均年假多少」
这类结构化问题。本章用同一份 org.json + employees.json 做三件事：
1. 建一张小型组织-技能图，做 2 跳查询（图部分仍是自定义邻接表）；
2. 用 LangChain 的 SQLDatabase 连接只读 SQLite，QuerySQLDatabaseTool / db.run 执行查询；
3. 用字典模拟 Text2Cypher，看清 GraphRAG 与图数据库的边界。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from langchain_community.tools import QuerySQLDatabaseTool
from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import employees, org

ALLOWED_TABLES = {"employees"}
DANGEROUS = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b", re.I)

# 岗位画像通常来自 JD 与用人经理确认；这里手写一份，避免把「什么算合格」藏进代码逻辑。
ROLE_PROFILE = {
    "算法组": {"must": ["RAG", "LLM", "向量检索"], "plus": ["Python", "PyTorch", "SQL"]},
}


def build_graph() -> dict[str, list[tuple[str, str]]]:
    """邻接表：节点是字符串，边是 (关系, 目标节点)，双向各存一条便于正反查。"""
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def link(head: str, relation: str, tail: str) -> None:
        adjacency[head].append((relation, tail))
        adjacency[tail].append((f"{relation}·逆", head))

    for dept in org()["departments"]:
        for child in dept.get("children", []):
            link(f"dept:{dept['name']}", "下设", f"dept:{child['name']}")
            link(f"dept:{child['name']}", "负责人", f"emp:{child['head']}")
    for emp in employees():
        link(f"dept:{emp['department']}", "归属", f"emp:{emp['id']}")
        for skill in emp["skills"]:
            link(f"emp:{emp['id']}", "具备", f"skill:{skill}")
        if emp["manager_id"]:
            link(f"emp:{emp['id']}", "汇报给", f"emp:{emp['manager_id']}")
    return adjacency


def find_skill_paths(graph: dict, dept: str, skill: str) -> list[list[str]]:
    """2 跳：部门 -归属-> 员工 -具备-> 技能。只允许沿指定关系走，避免图查询失控。"""
    paths: list[list[str]] = []
    for relation, employee in graph[f"dept:{dept}"]:
        if relation != "归属":
            continue
        for relation2, skill_node in graph[employee]:
            if relation2 == "具备" and skill_node == f"skill:{skill}":
                paths.append([f"dept:{dept}", employee, skill_node])
    return paths


def transfer_candidates(dept: str, role: str) -> list[dict]:
    """按岗位画像给部门内员工打分：must 命中优先，plus 是加分项。"""
    profile = ROLE_PROFILE[role]
    rows = []
    for emp in employees():
        if emp["department"] != dept or role[:2] in emp["position"]:
            continue  # 已在目标组（如算法工程师）不参与转岗打分
        must = sorted(set(emp["skills"]) & set(profile["must"]))
        plus = sorted(set(emp["skills"]) & set(profile["plus"]))
        if must or plus:
            rows.append({"name": emp["name"], "position": emp["position"],
                         "must": must, "plus": plus, "score": len(must) * 2 + len(plus)})
    return sorted(rows, key=lambda row: -row["score"])


def readonly_guard(action: int, arg1, arg2, dbname, source) -> int:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def build_db() -> SQLDatabase:
    """用 LangChain SQLDatabase 包住内存 SQLite；底层连接装 authorizer 做第二道只读闸门。"""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""CREATE TABLE employees (id TEXT PRIMARY KEY, name TEXT, department TEXT,
        position TEXT, level TEXT, city TEXT, join_date TEXT, annual_total INTEGER, annual_used INTEGER)""")
    conn.executemany(
        "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(e["id"], e["name"], e["department"], e["position"], e["level"], e["city"],
          e["join_date"], e["leave"]["annual_total"], e["leave"]["annual_used"]) for e in employees()],
    )
    conn.commit()  # SQLAlchemy 复用同一连接时，未提交的数据会被回滚
    engine = create_engine("sqlite://", creator=lambda: conn, poolclass=StaticPool)
    db = SQLDatabase(engine)
    conn.set_authorizer(readonly_guard)
    return db


def nl_to_sql(question: str) -> tuple[str, str]:
    """模板路由：先判断意图（count / list / avg），再拼受限的 SQL。

    真实系统这一步交给 LLM，输出 schema 约束下的 SQL；路由逻辑和校验逻辑不变。
    """
    q = question.replace(" ", "")
    conditions = []
    if "技术部" in q:
        conditions.append("department = '技术部'")
    if "上海" in q:
        conditions.append("city = '上海'")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    if "平均" in q:
        column = "annual_total" if "年假" in q else "annual_used"
        return "avg", f"SELECT ROUND(AVG({column}), 1) AS 平均值 FROM employees{where}"
    if "各部门" in q or "每个部门" in q:
        return "count", "SELECT department AS 部门, COUNT(*) AS 人数 FROM employees GROUP BY department ORDER BY 人数 DESC"
    if any(word in q for word in ("多少", "几个", "人数")):
        return "count", f"SELECT COUNT(*) AS 人数 FROM employees{where}"
    if any(word in q for word in ("谁", "名单", "列出", "哪些")):
        return "list", f"SELECT id, name, position, city FROM employees{where} ORDER BY id"
    return "list", "SELECT id, name, department FROM employees ORDER BY id"


def validate_sql(sql: str) -> str:
    """只允许单条 SELECT、只碰白名单表、没有 LIMIT 就自动补一个。"""
    text = sql.strip().rstrip(";").strip()
    if ";" in text:
        raise ValueError("不允许多条语句")
    if not re.match(r"(?is)^select\b", text):
        raise ValueError("只允许 SELECT")
    if DANGEROUS.search(text):
        raise ValueError("包含危险关键字")
    tables = {name.lower() for name in re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", text, re.I)}
    if not tables or not tables <= ALLOWED_TABLES:
        raise ValueError(f"表白名单拒绝：{sorted(tables) or '未识别'}")
    return text if "limit" in text.lower() else f"{text} LIMIT 100"


def run_sql(db: SQLDatabase, question: str) -> tuple[str, str, list[str], list[tuple]]:
    intent, sql = nl_to_sql(question)
    safe = validate_sql(sql)
    cursor = db.run(safe, fetch="cursor")  # fetch="cursor" 才有列名和原始行
    rows = [tuple(row) for row in cursor.fetchall()]
    return intent, safe, list(cursor.keys()), rows


def explain(intent: str, question: str, rows: list[tuple], columns: list[str]) -> str:
    """把结果翻译成人话。生产里这一步可以交给 LLM，但必须只基于 rows。"""
    if not rows:
        return "没有查到符合条件的数据。"
    if intent == "avg":
        return f"{question}：{rows[0][0]} 天（全表 {len(employees())} 人）"
    if "各部门" in question:
        return "；".join(f"{row[0]} {row[1]} 人" for row in rows)
    if intent == "count":
        return f"{question}：{rows[0][0]} 人"
    return "、".join(f"{row[1]}({row[0]})" for row in rows)


CYPHER_TEMPLATES = {
    "rag": """MATCH (d:Dept {name: '技术部'})<-[:BELONGS_TO]-(e:Employee)-[:HAS_SKILL]->(s:Skill {name: 'RAG'})
RETURN e.name AS 姓名, s.name AS 技能""",
    "transfer": """MATCH (e:Employee)-[:BELONGS_TO]->(d:Dept {name: '技术部'})
MATCH (e)-[:HAS_SKILL]->(s:Skill)
WHERE s.name IN ['RAG', 'LLM', '向量检索', 'Python', 'SQL']
RETURN e.name AS 姓名, collect(s.name) AS 命中技能, size(collect(s.name)) AS 命中数
ORDER BY 命中数 DESC LIMIT 10""",
}


def text_to_cypher(question: str) -> tuple[str, str]:
    """用字典模拟 Text2Cypher：命中不了模板就返回空，说明需要人工或 LLM 兜底。"""
    if "RAG" in question:
        return "rag", CYPHER_TEMPLATES["rag"]
    if "转岗" in question:
        return "transfer", CYPHER_TEMPLATES["transfer"]
    return "", ""


def main() -> None:
    def section(title: str) -> None:
        print(f"\n=== {title} ===")
    section("1. 建图：把部门、员工、技能连起来")
    graph = build_graph()
    print(f"节点 {len(graph)} 个，边 {sum(len(items) for items in graph.values())} 条")
    print(f"技术部一度邻居：{graph['dept:技术部'][:4]} …")
    section("2. 2 跳查询：技术部谁具备 RAG 经验")
    paths = find_skill_paths(graph, "技术部", "RAG")
    for path in paths:
        employee_id = path[1].split(":")[1]
        person = next(e for e in employees() if e["id"] == employee_id)
        print(f"  技术部 --归属--> {person['name']}({employee_id}) --具备--> RAG")
    names = [path[1].split(":")[1] for path in paths]
    print(f"命中 {len(paths)} 人：{names}")
    section("3. 可转岗：技术部 -> 算法组（must 命中 2 分，plus 命中 1 分）")
    print("  已在算法组的孙悦不参与打分，只看其他成员：")
    for row in transfer_candidates("技术部", "算法组"):
        print(f"  {row['name']}（{row['position']}）must={row['must']} plus={row['plus']} 得分={row['score']}")
    section("4. Text2SQL：LangChain SQLDatabase + 模板路由")
    db = build_db()
    tool = QuerySQLDatabaseTool(db=db)
    for question in ["技术部有多少人", "上海有哪些员工", "员工平均年假有多少天", "各部门人数"]:
        intent, safe, columns, rows = run_sql(db, question)
        print(f"\n  问：{question}\n  意图：{intent}\n  SQL：{safe}")
        print(f"  列：{columns}\n  结果：{rows}")
        print("  解释：" + explain(intent, question, rows, columns))
    print("\n  QuerySQLDatabaseTool 直查：" + str(tool.invoke("SELECT COUNT(*) AS 人数 FROM employees")))
    section("5. 安全闸门：DROP TABLE 会被拦两次")
    try:
        validate_sql("DROP TABLE employees")
    except ValueError as exc:
        print(f"  校验层拒绝：{exc}")
    try:
        db.run("DROP TABLE employees")
    except Exception as exc:  # SQLAlchemy 会把 sqlite 的 not authorized 包一层
        print(f"  authorizer 层拒绝：{type(exc).__name__}: {str(exc).splitlines()[0]}")
    print(f"  补 LIMIT 演示：{validate_sql('SELECT * FROM employees')}")
    section("6. Text2Cypher：同样的意图换成图查询")
    for question in ["技术部谁有 RAG 经验", "谁可以向算法组转岗"]:
        name, cypher = text_to_cypher(question)
        print(f"\n  问：{question}\n  模板：{name or '未命中，需人工兜底'}\n{cypher}")
    assert names == ["E1007"], "2 跳查询应只命中孙悦（E1007）"
    assert any(row["name"] == "林小雨" for row in transfer_candidates("技术部", "算法组")), "林小雨应有转岗潜力"
    assert validate_sql("SELECT * FROM employees").endswith("LIMIT 100")
    blocked = False
    try:
        validate_sql("DROP TABLE employees")
    except ValueError:
        blocked = True
    assert blocked, "DROP TABLE 必须被校验层拒绝"
    print("\n断言通过：LangChain SQL 链路、2 跳查询、只读闸门三道结论都成立。")


if __name__ == "__main__":
    main()