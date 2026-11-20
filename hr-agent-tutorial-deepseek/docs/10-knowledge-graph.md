---
title: "10 | 知识图谱与 Text2SQL：组织、技能与数据查询"
slug: "knowledge-graph"
order: 10
part: "RAG 与知识工程"
minutes: 70
difficulty: "高阶"
prerequisites: ["09"]
summary: "把组织与技能建成小型知识图谱做多跳查询，并给 Text2SQL 装上只读闸门。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`SQLDatabase`、`QuerySQLDatabaseTool`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch10_text2sql.py`。


## 0. 本章你会得到什么

学完这一章，你应该能：

1. 把「部门—员工—技能」建成一张邻接表形式的小型知识图谱，并写出 2 跳查询。
2. 说清知识图谱适合回答哪类问题、向量检索为什么答不了。
3. 用模板路由把自然语言变成 SQL，覆盖 `count` / `list` / `avg` 三类常见意图。
4. 给 SQL 加三道防线：只允许 SELECT、表白名单、自动 LIMIT；再用 SQLite authorizer 兜底。
5. 知道 Text2Cypher 与 GraphRAG 的适用边界，不会为了「看起来高级」而上图数据库。

> 📌 **考点**：面试官常问「什么场景该用知识图谱而不是向量库」。能答出「多跳关系、精确聚合、可解释路径」三点，并主动说出「小数据量用 SQL 就够，别上 Neo4j」，会让回答更可信。

## 1. 场景

2026 年 4 月，Acme 科技的 CEO 在季度会上问了一个问题：

> 技术部现在有几个人具备 RAG 经验？如果算法组要补人，内部谁可以转岗？

HRBP 赵敏花了整整两天：先在 HR 系统导出 16 名员工，再翻岗位说明书，再一个个问技术总监徐明，最后拼出一张 Excel。等她答复时，CEO 已经在会上用了另一个数字。

这个问题暴露了两个短板：

- **它是关系问题，不是文本问题。** 「技术部」包含哪些人、每个人会什么、算法组需要什么，是三张表之间的连接。向量检索只能找到「提到 RAG 的段落」，找不到「谁具备 RAG 技能」。
- **它需要精确答案。** 「大概有两个人」在 CEO 面前没有意义，必须给出姓名、工号、证据路径。

更麻烦的是，这类问题每天都有变体：「上海有多少人」「各部门平均年假多少天」「P6 以上有多少人」。如果每个问题都写一次代码，HR 会被需求淹没；如果让模型直接连数据库，又可能一条 `DROP TABLE` 把生产库删了。赵敏真正需要的不是「更聪明的搜索框」，而是一个**能查关系、能算数字、还不会闯祸**的查询入口。

这一章我们同时解决两件事：**关系用图查，数字用 SQL 查，但 SQL 必须过安检。**

## 2. 概念

### 2.1 知识图谱：实体 + 关系

知识图谱（Knowledge Graph）听起来玄，本质是一张「点—边」表：

- **实体（Entity）**：部门、员工、技能、岗位。每个实体有唯一标识，比如 `dept:技术部`、`emp:E1007`、`skill:RAG`。
- **关系（Relation）**：归属、具备、下设、汇报给。关系有方向，`员工 --归属--> 部门` 和 `部门 --下设--> 子部门` 是两种不同的边。
- **本体（Ontology）**：事先约定「有哪些实体类型、允许哪些关系」。它决定了图能不能被稳定查询，也决定了后面 Text2Cypher 的模板怎么写。

本章的图长这样：

```text
                         ┌──────────────┐
                         │ dept:技术部   │
                         └──────┬───────┘
                  下设 │        │ 归属
          ┌────────────┼────────┼──────────────┐
          ▼            ▼        ▼              ▼
   ┌────────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐
   │ dept:算法组 │ │ emp:E1007│ │ emp:E1001 │ │ emp:E1011 │
   └──────┬─────┘ │ 孙悦     │ │ 张伟      │ │ 林小雨    │
          │ 负责人  └────┬─────┘ └────┬─────┘ └────┬─────┘
          └──────────────┘            │            │
                          具备 │       │ 具备        │ 具备
                               ▼       ▼            ▼
                        ┌────────┐ ┌────────┐ ┌────────┐
                        │skill:  │ │skill:  │ │skill:  │
                        │RAG     │ │Python  │ │SQL     │
                        └────────┘ └────────┘ └────────┘
```

「技术部谁具备 RAG 经验」就是一次 2 跳：`技术部 --归属--> 员工 --具备--> RAG`。如果问「谁可以向算法组转岗」，还要再加一跳：算法组需要什么技能，候选人的技能和它差多少。**跳数就是图的查询深度，也是它比向量检索更适合关系问题的原因。**

图的存法有三种常见选择。第一种是**邻接表**（adjacency list），也是本章用的：一个字典，键是节点，值是 `(关系, 目标)` 列表。它最轻，几十万条边都能放进内存，但只适合本机、单进程。第二种是**三元组表**（subject, predicate, object），可以直接落到关系库，靠索引查，适合需要事务和持久化的场景。第三种是**属性图**（property graph），节点和边都能挂属性，Neo4j、Nebula 属于这一类，支持 Cypher 和路径查询，代价是运维复杂度。

选哪种不看「哪个更先进」，看查询形态：本章的查询都是「从一个部门出发，沿固定关系走 1~2 跳」，邻接表足够；如果查询变成「找两个员工之间的最短路径」「按关系类型统计全图」，就该换属性图。另外要记住：2 跳的复杂度是 `度数 × 度数`，3 跳可能直接爆炸。生产里的图查询必须限制关系类型、跳数和返回条数，否则一个「查一下全公司关系」就能把服务打挂。

### 2.2 Text2SQL：把问题翻译成 SQL

Text2SQL 的完整链路比「让模型写 SQL」长得多：

```text
自然语言
   │
   ▼
意图识别（count / list / avg / 其他）
   │
   ▼
Schema 链接：问题里的「技术部」对应 employees.department
   │
   ▼
SQL 生成（模板或 LLM）
   │
   ▼
┌──────────────── 安全闸门 ────────────────┐
│ 1. 只允许单条 SELECT                      │
│ 2. 表白名单：只能碰 employees              │
│ 3. 危险关键字：DROP/DELETE/UPDATE/PRAGMA  │
│ 4. 没有 LIMIT 自动补 LIMIT 100            │
│ 5. SQLite authorizer：语句级只读          │
│ 6. 只读连接 / 查询超时 / 结果行数上限      │
└──────────────────────────────────────────┘
   │
   ▼
执行 → 结果 → 用模板解释成人话
```

本章用模板路由实现前三类意图，原因是：**教学要先把「安全边界」讲透，再谈模型能力**。真实系统里 SQL 由 LLM 生成，但生成之后的校验、白名单、LIMIT、只读连接一个都不能少。模型越强，越需要闸门——因为它更会写出「看起来合理」的危险语句。

真正难的一步是 **schema linking**：把「技术部」映射到 `department = '技术部'`，把「年假」映射到 `annual_total`，把「平均」映射到 `AVG`。这一步错了，SQL 语法再漂亮也是错的。举个例子：用户问「研发有多少人」，如果库里存的是「技术部」，模板路由会直接生成全表 `COUNT`，答案变成 16——数字没错，含义全错。所以生产系统必须在生成 SQL 之前，先把「实体映射结果」显式打印或记录，关键字段（部门、职级、城市）还要做枚举校验：值不在枚举里就拒绝，而不是硬猜。

### 2.3 Text2Cypher 与 GraphRAG 的边界

- **Text2Cypher**：把自然语言翻成 Cypher（Neo4j 的查询语言）。适合「关系路径明确、schema 稳定」的问题，比如「谁向谁汇报」「某技能的人才分布」。
- **GraphRAG**：先从文档里抽实体和关系建图，再对社区做摘要，回答「这份 300 页的制度里，哪些条款互相引用」这类全局问题。它解决的是「跨文档关联」，不是「查员工表」。
- **什么时候不该上图**：实体少于几万、关系只有一两层、查询主要是聚合统计——SQL 更快、更省、更容易维护。图数据库的价值在**多跳**和**路径解释**，不在「听起来高级」。

> ⚠️ **生产提醒**：图查询一定要限制「关系类型、最大跳数、返回条数」三个参数。不限制的话，一句「查一下这个人和公司的所有关系」就可能沿着边遍历几十万节点，把图数据库拖垮。Cypher 里的变长路径 `[:REPORTS_TO*1..5]` 尤其危险，跳数上限必须写死。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


运行：

```bash
python code/ch10_text2sql.py
```

实际输出（节选）：

```text
=== 1. 建图：把部门、员工、技能连起来 ===
节点 84 个，边 208 条
技术部一度邻居：[('下设', 'dept:后端组'), ('下设', 'dept:前端组'), ('下设', 'dept:算法组'), ('下设', 'dept:质量组')] …

=== 2. 2 跳查询：技术部谁具备 RAG 经验 ===
  技术部 --归属--> 孙悦(E1007) --具备--> RAG
命中 1 人：['E1007']

=== 3. 可转岗：技术部 -> 算法组（must 命中 2 分，plus 命中 1 分） ===
  已在算法组的孙悦不参与打分，只看其他成员：
  林小雨（数据工程师）must=[] plus=['Python', 'SQL'] 得分=2
  张伟（后端工程师）must=[] plus=['Python'] 得分=1

=== 4. Text2SQL：内存 SQLite + 模板路由 ===
  问：技术部有多少人
  SQL：SELECT COUNT(*) AS 人数 FROM employees WHERE department = '技术部' LIMIT 100
  结果：[(6,)]
  解释：技术部有多少人：6 人

  问：员工平均年假有多少天
  SQL：SELECT ROUND(AVG(annual_total), 1) AS 平均值 FROM employees LIMIT 100
  结果：[(11.9,)]
  解释：员工平均年假有多少天：11.9 天（全表 16 人）

=== 5. 安全闸门：DROP TABLE 会被拦两次 ===
  校验层拒绝：只允许 SELECT
  authorizer 层拒绝：not authorized
  补 LIMIT 演示：SELECT * FROM employees LIMIT 100
```

三个关键实现。邻接表用「双向各存一条边」，正向查「技术部有哪些人」，反向查「孙悦属于哪个部门」都不用再写一遍逻辑：

```python
    def link(head: str, relation: str, tail: str) -> None:
        adjacency[head].append((relation, tail))
        adjacency[tail].append((f"{relation}·逆", head))
```

2 跳查询只允许沿指定关系走，避免图查询变成「随便遍历」：

```python
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
```

SQL 校验是本章最重要的一段，注意它把「单条语句」也当成了检查项：

```python
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
```

第二道防线在连接层：`PRAGMA query_only = ON` 之后，再用 `set_authorizer` 只放行 `SELECT`、`READ`、`FUNCTION` 三类动作。即使有人绕过 `validate_sql` 直接调 `conn.execute("DROP TABLE employees")`，SQLite 也会抛 `not authorized`。

脚本用 `:memory:` 内存库，是为了让「建表 → 插入 → 查询 → 拦截」在一条命令里跑完，不留下任何临时文件。真实项目里换成 PostgreSQL/MySQL 时，`validate_sql` 和 authorizer 的职责要重新分配：MySQL 没有等价的内置 authorizer，需要用只读账号 + `SELECT` 权限 + 独立只读副本 + 查询超时来达到同样效果。**换数据库时，安全模型要重新实现，不能假设「照着抄一遍就行」。**

## 4. 逐行拆解

**第一，为什么用字符串节点而不是对象。** `dept:技术部`、`emp:E1007` 这种带前缀的字符串，既能当字典键，又能在打印时直接看出类型。缺点是丢了类型检查，生产里建议用 `Node(type, id)` 或图数据库的标签。教学版取「一眼看懂」，是有意的取舍。

**第二，为什么转岗要引入岗位画像。** 「可转岗」不是「技能有重叠」这么简单：算法组要的是 RAG、LLM、向量检索（must），Python、PyTorch、SQL 是加分项（plus）。把 must 和 plus 分开，才能解释「林小雨为什么能转、还差什么」——她 SQL 和 Python 都熟，但 must 一个没中，需要补 RAG/LLM。如果只算一个总分，HR 看不出培训重点。

**第三，为什么孙悦不参与转岗打分。** 她已经在算法组，把她算成「可转岗」是重复计数。代码用 `role[:2] in emp["position"]` 做了个粗糙的排除，生产里应该用「当前部门 ID == 目标部门 ID」判断，而不是猜岗位名。这个粗糙之处值得在代码评审时被指出来。

**第四，为什么两道 SQL 闸门都要。** `validate_sql` 是字符串检查，能被注释、大小写、Unicode 绕过；authorizer 是数据库内核层的动作检查，绕不过去。但 authorizer 只保护「这一条连接」，如果程序里另开了可写连接，它也没用。所以生产里还要：只读账号、独立只读副本、查询超时、结果行数上限——**纵深防御，每一层都假设上一层会失效**。

**第五，为什么结果要再解释一遍。** `[(6,)]` 对 HR 没有意义，`技术部有多少人：6 人` 才有。解释层只允许基于 `rows` 说话，不能自己加「大概」「约」这类修饰。生产里这一步可以交给 LLM，但输入必须只有 `columns + rows + 原始问题`，并且要求「数字必须来自结果」。

**第六，为什么「编制」和「花名册」要先对账。** `org.json` 里技术部的 `headcount` 是 7，但 `employees.json` 里 `department == "技术部"` 的员工只有 6 人（含技术总监）。差的 1 个是「在招编制」还是「数据没同步」，图本身不知道。如果直接拿 `headcount` 回答「技术部有多少人」，就会和 SQL 查出来的 6 打架。本章统一用花名册（employees）作为人数口径，并在文档里写明；生产里应该把「编制数」「在职数」「在招数」分成三个字段，各自带口径说明。**图查询最怕的不是查不到，是两个数据源各说各话。**

## 5. 实验

**实验一：加一个「按城市统计」。** 在 `nl_to_sql` 里加一条规则：问题含「各城市」时生成 `GROUP BY city`。再问「各城市有多少人」，检查结果是否和 `employees.json` 手算一致。提示：注意「上海」既可能是筛选条件，也可能是分组维度，模板路由要能区分「按城市」和「在上海」。

**实验二：给查询加超时。** SQLite 的 `set_progress_handler` 可以每 N 条指令回调一次，在回调里检查耗时并返回非 0 中断查询。给执行查询的代码加 0.2 秒超时，再构造一条笛卡尔积查询（`FROM employees a, employees b, employees c`）验证它会被中断。

**实验三：扩一张表。** 新建 `departments(id, name, head_id)`，把 `employees.department` 换成 `department_id`，再让「各部门人数」走 `JOIN`。观察 `validate_sql` 的白名单是否需要同步更新——这就是「schema 变了，闸门也要变」的真实工作量。

**实验四：把模板路由换成 LLM。** 用 `MockChatModel` 返回一条 SQL 字符串（第一次故意返回 `DELETE FROM employees`），走一遍 `validate_sql`，看它被拒绝后如何重试。思考：重试几次？谁来决定放弃？

## 6. 工程化视角

- **图数据库的选型**：实体规模在 10 万以内、查询以 2 跳为主，PostgreSQL 的递归 CTE 或内存邻接表就够。上万实体、需要路径解释和社区摘要时再考虑 Neo4j。不要因为「GraphRAG」这个词就上图。
- **Schema 即契约**：`employees` 表字段、`dept/emp/skill` 的关系名，都是要版本化的契约。加字段要同步更新：SQL 模板、白名单、前端列名、评测用例。
- **Schema 链接**：用户说「技术部」，表里存的是「技术部」，这是最简单的；用户说「研发」「技术团队」，就需要同义词表或 LLM 做映射。映射错了，SQL 语法再对也是错的。
- **只读与审计**：Text2SQL 必须走只读账号/只读副本；每次查询记录「谁问的、生成了什么 SQL、扫了多少行、耗时多少」。L2/L3 字段（薪资、绩效）要在 SQL 层就过滤掉，而不是查出来再脱敏。
- **结果上限**：除了 `LIMIT`，还要限制返回字节数和列数。有人问「把所有人的简历给我」，即使 SQL 合法也不该返回。
- **GraphRAG 的位置**：它适合「跨文档的全局问题」，比如「过去两年哪些制度修改过试用期条款」。这类问题用本章的图 + 文档引用组合更合适：图负责找实体，RAG 负责找原文。
- **评测要分两类**：图查询测「路径是否正确、结果是否可解释」；Text2SQL 测「意图识别、schema linking、SQL 执行成功率、结果正确率」。两类指标的失败原因完全不同，混在一起看会误导优化方向。至少准备 30 条带标准答案的问题，每次改模板或换模型都跑一遍。

> ⚠️ **生产提醒**：永远不要用应用的主库账号执行模型生成的 SQL。只读副本 + 独立账号 + 语句超时，是最低配置。见过太多「Demo 里能跑，上线删了表」的事故。

## 7. 常见坑

**现象：`SELECT * FROM employees` 能跑，但结果 10 万行把内存打爆。**
原因：只做了语法校验，没做结果规模控制。
解法：自动 LIMIT + 最大行数 + 最大列数 + 超时；对 `SELECT *` 直接要求列出字段。

**现象：中文列名在 `cursor.description` 里变成乱码。**
原因：连接或终端编码不一致。
解法：数据库连接统一 UTF-8；列名用英文，展示层再做中文映射。本章为了教学直接用了中文别名，生产里不推荐。

**现象：`validate_sql` 被注释绕过。**
原因：`SELECT 1; --` 或 `/* */` 拼接。
解法：先拒绝 `;` 和多语句，再用 AST 解析器（如 `sqlglot`）而不是正则；authorizer 作为最后一道。

**现象：2 跳查询返回了重复的人。**
原因：一个人有多个技能，路径按「员工×技能」展开，同一个人出现多次。
解法：在业务层按 `employee_id` 去重；或者查询时用 `DISTINCT`，但要注意 `DISTINCT` 会丢掉「命中哪些技能」的信息，最好保留技能列表再聚合。

**现象：Text2SQL 生成的 SQL 语法正确，但业务含义错。**
原因：schema linking 错了，比如把「技术部」映射成了 `department = '技术'`。
解法：生成 SQL 前先把实体映射结果打印/记录出来；对关键字段（部门、职级、城市）做枚举校验，不在枚举里就直接拒绝。

**现象：图里的人数、SQL 里的人数、HR 系统里的人数三个都不一样。**
原因：数据源不同步，且没有定义「人数」口径（在职/含实习/含编制）。
解法：先定口径再建图，字段命名上体现口径（`headcount_active`、`headcount_plan`）；每次查询结果附带数据时间戳和数据源，让用户知道自己在看哪一份账。

## 8. 练习

**练习 1（易）**：在图上查「孙悦汇报给谁」，写出 1 跳查询，并说明为什么不需要 2 跳。

<details><summary>参考答案</summary>

`graph["emp:E1007"]` 里找关系为 `汇报给` 的边，目标是 `emp:E2001`（徐明）。1 跳就够，因为「汇报给」是直接边；只有需要「通过谁」才能到达的目标才需要多跳。多跳的成本是组合爆炸，跳数越多越要限制关系类型和深度。
</details>

**练习 2（中）**：给 `transfer_candidates` 加一个「差距清单」：输出候选人还缺哪些 must 技能，按缺口数量排序。

<details><summary>参考答案</summary>

`missing = sorted(set(profile["must"]) - set(emp["skills"]))`，排序键用 `(len(missing), -score)`。对林小雨，missing 是 `['LLM', 'RAG', '向量检索']`，缺口 3 项；这比一个「得分 2」更能指导培训计划。注意别把 plus 也算进缺口，否则会误导 HR 认为必须全会。
</details>

**练习 3（中）**：给 SQL 加超时（`set_progress_handler`），并写一条测试证明死循环/笛卡尔积会被中断。

<details><summary>参考答案</summary>

```python
def make_guard(deadline: float):
    def handler() -> int:
        return 1 if time.monotonic() > deadline else 0
    return handler

conn.set_progress_handler(make_guard(time.monotonic() + 0.2), 1000)
```

回调返回非 0 会中断当前语句并抛 `sqlite3.OperationalError: interrupted`。测试时构造 `SELECT COUNT(*) FROM employees a, employees b, employees c`，断言 0.2 秒左右抛异常。生产里超时时间要按查询类型配置，报表类可以放宽。
</details>

**练习 4（难）**：设计一个「HR 数据问答」的权限模型：哪些角色能查哪些字段？如何防止「用聚合查询反推个人薪资」？

<details><summary>参考答案</summary>

按角色分级：普通员工只能查自己的记录；HRBP 可查所支持部门，但薪资、绩效等 L2 字段默认脱敏；HR 总监可查全公司汇总。防反推的手段：对小于 5 人的分组不返回结果（k-匿名）；禁止对敏感字段做 `MIN/MAX/AVG` 的细粒度分组；所有查询记录审计日志；敏感字段单独授权 + 二次审批。权限判断要在 SQL 生成前完成，不要指望「查出来再删列」。
</details>

## 9. 小结与下一章

- 知识图谱解决「多跳关系 + 可解释路径」，SQL 解决「精确聚合」；两者都不替代 RAG，而是补它的短板。
- Text2SQL 的难点不在生成，而在**约束**：单条 SELECT、表白名单、自动 LIMIT、只读连接、超时与行数上限，一层都不能少。
- 转岗这类问题要拆成「must / plus」和「缺口清单」，只给一个总分，HR 没法用。

能查数据不等于能上生产：邮件会超时、接口会重复、下游会整体挂掉。下一章我们给这些外部依赖加上重试、幂等、熔断和降级，让批量任务在故障中也能给出确定结果。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **SQLDatabase + QuerySQLDatabaseTool**，完整代码见 `code/ch10_text2sql.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_community.utilities import SQLDatabase

db = SQLDatabase(engine=engine)
tool = QuerySQLDatabaseTool(db=db)
sql = validate_sql(nl_to_sql("技术部有多少人"))   # 只允许 SELECT + 白名单
rows = db.run(sql, fetch="cursor").fetchall()
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 数据库 | `SQLDatabase` |
| 查询工具 | `QuerySQLDatabaseTool` |
| 安全 | 自定义白名单 + 只读 |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch10_text2sql.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
