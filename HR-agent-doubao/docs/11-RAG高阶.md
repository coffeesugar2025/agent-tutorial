# 11 · RAG 高阶：结构化知识、Text2SQL、Text2Cypher

## 11.1 本章目标

1. 判断一个问题该走 **RAG** 还是 **SQL/图查询**——这是本章最值钱的一分钟；
2. 用 `SQLDatabase` 自动读出表结构，喂给模型；
3. 用 `with_structured_output(Query)` 让模型只输出 SQL + 口径，不输出解释；
4. 三层护栏：只读、表白名单、审计——把 SQL 执行做成"不可能出事"。

跑法：`python ch11_text2sql/main.py`

## 11.2 一句话判据

```
"技术中心现在有多少人？"
  · RAG 会给一段"技术中心负责…"的描述 —— 没有数字，无法回答
  · SQL 会给 3（在职口径：status='active' 且 dept='技术中心'）
```

| 问法 | 走哪条路 |
|---|---|
| 多少个 / 多少天 / 排名 / 占比 / 趋势 | **SQL** |
| 规定是什么 / 怎么走流程 / 有什么要求 | **RAG** |
| 谁会影响 X 的交付 / 技能-岗位-项目三角 | **图查询** |

★ 数字类问题必须走结构化查询。**向量库永远算不准聚合。**

## 11.3 `SQLDatabase`：schema 自动喂给模型

```python
from langchain_community.utilities import SQLDatabase

db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH.as_posix()}", include_tables=["emp", "leave_bal"])
SCHEMA = db.get_table_info()
```

实测输出（直接从库里读出来的）：

```
    CREATE TABLE emp (
      emp_id TEXT,
      name TEXT,
      dept TEXT,
      city TEXT,
      level TEXT,
      status TEXT,
      hired_at TEXT
```

`include_tables` 很重要：**只暴露该暴露的表**。默认暴露全库，等于把薪资表也告诉了模型。

## 11.4 Text2SQL：契约里必须带口径

```python
class Query(BaseModel):
    sql: str = Field(description="一条只读 SQL，禁止 INSERT/UPDATE/DELETE")
    caliber: str = Field(description="口径说明：统计范围、过滤条件，一句话")
    tables: list[str] = Field(description="用到的表名")
```

为什么强制模型写 `caliber`？因为 HR 数据 90% 的争议在口径上：

- "技术中心有多少人"——在职的？含实习？含外包？含待入职？
- 模型写 `SELECT COUNT(*) FROM emp WHERE dept='技术中心'` 是错的（把离职的赵敏也算进去了）。

实测：

```
  SQL：SELECT COUNT(*) AS n FROM emp WHERE dept='技术中心' AND status='active'
  口径：统计技术中心在职（status=active）员工数，不含已离职
  用到的表：['emp']
```

## 11.5 三层护栏

```python
def guarded_exec(cur, query: Query) -> list[tuple]:
    sql = query.sql.strip()
    if not sql.upper().startswith(("SELECT", "WITH")):
        raise PermissionError("只允许 SELECT / WITH 开头的只读查询")
    for bad in ("INSERT","UPDATE","DELETE","DROP","ALTER","ATTACH","PRAGMA"):
        if bad in sql.upper():
            raise PermissionError(f"命中危险关键字：{bad}")
    if not set(query.tables) <= ALLOWED_TABLES:
        raise PermissionError(f"越权访问表：{set(query.tables) - ALLOWED_TABLES}")
    rows = cur.execute(sql).fetchall()
    audit.append({"sql": sql, "rows": len(rows), "caliber": query.caliber})
    return rows
```

实测两个攻击都被拦：

```
  恶意 SQL 被拦：只允许 SELECT / WITH 开头的只读查询
  越权表被拦：越权访问表：{'salary_secret'}
  ★ Text2SQL 的安全不靠 prompt，靠'执行层'：只读、白名单、审计三件套
```

**必须补的两条**（demo 里没做，生产必做）：

1. **只读账号**：数据库层面就用一个没有写权限的账号。字符串检查只是第二道闸。
2. **行级权限**：`WHERE dept = 调用者的部门`。不然一个业务中心的人能查到全公司薪资。

## 11.6 Text2Cypher / GraphRAG：什么时候真需要图

用 dict 模拟三元组（生产换 Neo4j + `langchain-neo4j` 的 `Neo4jGraph`）：

```python
triples = [
    ("E1001", "任职于", "技术中心"),
    ("E1001", "汇报给", "E1003"),
    ("E1003", "负责", "前端平台"),
    ("前端平台", "依赖", "设计系统"),
    ("C1024", "应聘", "P1001"),
    ("P1001", "属于", "前端平台"),
]
```

两跳邻居查询："谁会影响前端平台的交付"——SQL 要写三层 JOIN，图上一步就够。

| 图的强项 | 图的成本 |
|---|---|
| 多跳关系、影响面分析 | 三元组抽取要人审（LLM 抽的关系一半是错的） |
| 组织架构、技能-岗位-项目三角 | 维护成本高，schema 会漂移 |
| "谁汇报给谁、谁依赖谁" | 数据更新链路复杂 |

**经验判据：先把 SQL 做扎实，出现"要 3 跳以上才能答"的问题，再考虑图。**

## 11.7 GraphRAG 的真实门槛

1. **本体（Ontology）设计**：实体类型、关系类型要人工定，不是让模型自由发挥。
2. **抽取质量**：一段 JD 里"要求 Vue3 经验"是技能关系，"3-5 年"是约束。LLM 经常把约束抽成关系。
3. **增量更新**：员工离职、调岗，图要跟着变。
4. **评测**：图查询的"答对"标准比 RAG 更难定。

所以真实项目里 GraphRAG 通常只用在**一个垂直场景**（如"故障归因""技能图谱"），而不是全公司铺开。

## 11.8 常见坑

1. **schema 全暴露**：`include_tables` 不设，等于把敏感表结构告诉模型。
2. **不校验表白名单**：模型可以写 `SELECT * FROM salary`。
3. **不记审计**：出了问题无法复盘"是谁在什么时候查了什么"。
4. **口径没落库**：同一个"在职人数"两个报表给两个数，就是口径没写清。
5. **以为 Text2SQL 能替代 RAG**：政策类问题它答不了。

## 11.9 自检清单

- [ ] 能用一句话判断该走 RAG 还是 SQL
- [ ] 知道 `include_tables` 的作用
- [ ] 能说出三层护栏分别防什么
- [ ] 理解 GraphRAG 的成本与适用边界

## 11.10 练习

1. 跑"各部门在职人数"，检查 `caliber` 是否把"在职"写清。
2. 给 `guarded_exec` 加 dry-run（`EXPLAIN`），先看代价再执行。
3. 用 `langchain-neo4j` 的 `Neo4jGraph` 替换 `triples`，跑通一条 Text2Cypher。
