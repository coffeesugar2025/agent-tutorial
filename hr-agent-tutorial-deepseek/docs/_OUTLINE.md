# 课程大纲（写作依据）

> **2026-11 重要更新**：全书 demo 已改为 **LangChain 1.x + LangGraph 1.x**。本文件里“手写循环 / 不写框架 / 不用 LangChain”等旧表述作废，统一遵循 `docs/_LANGCHAIN_MIGRATION.md`。章节主题、业务场景、学习目标不变，代码实现与第 3 节说明按迁移文档改写。

总目标：让一个零基础读者，沿着 HR 业务场景，从“会调模型”走到“能交付可验收的 Agent 系统”，并具备求职作品集与面试表达能力。

技术栈：Python 3.12 + FastAPI + Vue 3 + SQLite + 纯 Python 检索。默认离线可跑（MockLLM），可切换任意 OpenAI 兼容模型。

统一约定：
- 文档路径：`docs/<两位序号>-<slug>.md`
- 代码路径：`code/ch<两位序号>_<name>.py`
- 所有代码从 `code/` 目录导入 `common`，用 `MockLLM` 离线演示。
- 每章 frontmatter 的 `part` 必须使用下面五个之一。

---

## 第一部分 · 启程：从 HR 痛点理解 Agent

### 00 | 从 HR 痛点出发：Agent 到底是什么
- 文件：`docs/00-course-map.md`，代码：`code/ch00_hello_agent.py`
- slug：`course-map`，order：0，minutes：40，difficulty：入门，prerequisites：[]
- 学习目标：
  1. 用自己的话解释 Agent 与聊天机器人的区别：能观察、能决策、能行动、能验收。
  2. 画出 HR 智能服务台的五层架构：交互层、Agent 层、工具层、知识层、治理层。
  3. 跑通第一个 30 行 Agent：查制度 → 查余额 → 给建议。
  4. 知道全书 18 章分别在解决哪个工程问题。
- 场景：HR 共享服务中心每天收到 200+ 重复咨询，员工问“年假还剩几天、能不能请、怎么请”。人工答复慢、口径不一；买一个“知识库问答”又只会背书，不会查余额、不会提交申请。
- 必讲概念：生成式 AI 的能力边界；Agent 四要素（Goal / Loop / Tools / Memory）；“会说话”与“会办事”的区别；Human-in-the-loop 的边界；本书技术栈地图。
- 代码任务：写一个最小 `run_agent`：系统提示 + 两个工具（`get_leave_balance`、`search_policy`）+ 最多 4 步循环；`MockLLM` 脚本先调余额、再调制度、最后总结；用 `Tracer` 打印调用树。
- 关键图：`员工一句话 → Agent Loop → 工具/知识 → 回答 + 引用 + 待办`；全书章节地图。
- 练习：把工具换成“查工单”；把最大步数改成 1 观察失败；给 Agent 加一条“无证据必须拒答”的规则。
- 衔接：本章只让你“看见”循环，第 01 章补 LLM 与 Prompt 的基本功。

### 01 | LLM 与 Prompt：把 JD 变成结构化数据
- 文件：`docs/01-llm-prompt.md`，代码：`code/ch01_structured_output.py`
- slug：`llm-prompt`，order：1，minutes：50，difficulty：入门，prerequisites：["00"]
- 学习目标：
  1. 理解 messages、role、token、temperature、上下文窗口。
  2. 写出可复用的 Prompt 模板：角色、任务、输入、约束、输出格式、示例。
  3. 用 Pydantic 校验 JSON，失败自动重试一次。
  4. 估算一次调用的 token 成本，知道为什么要做模型路由。
- 场景：招聘专员每天把 30 份 JD 手工录入系统，字段漏填、格式不一；用 LLM 抽取成岗位卡片，但模型偶尔返回多余解释或漏字段。
- 必讲概念：Token 是什么；system/user/assistant；JSON Mode 与结构化输出；few-shot；温度；校验与重试；Prompt 注入的初级防范。
- 代码任务：定义 `JobCard` Pydantic 模型（title、department、city、level、skills、min_years、salary_min/max、responsibilities）；`MockLLM` 第一次返回带 markdown 的坏 JSON，第二次返回合法 JSON；实现 `extract_job_card()` 的解析、校验、重试、成本统计；用 3 个 JD 演示。
- 关键图：`JD 文本 → Prompt → LLM → JSON → Pydantic 校验 → 重试/入库`。
- 练习：增加 `must_have` 字段；把 temperature 从 0 调到 0.9 观察稳定性；为失败样本写一条更明确的约束。
- 衔接：会稳定产出结构化数据后，下一章让模型开始“调用工具”。

---

## 第二部分 · 单 Agent 核心

### 02 | Agent Loop：让模型学会“再来一轮”
- 文件：`docs/02-agent-loop.md`，代码：`code/ch02_agent_loop.py`
- slug：`agent-loop`，order：2，minutes：55，difficulty：入门，prerequisites：["01"]
- 学习目标：
  1. 手写 while 循环：模型返回工具调用 → 执行 → 结果回填 → 再问模型。
  2. 设计终止条件：拿到最终答案、达到最大步数、工具连续失败、超时。
  3. 理解消息序列中 assistant/tool 消息的配对关系。
  4. 用 Trace 看见每一轮发生了什么。
- 场景：员工问“我下个月想休 3 天年假，够不够？需要提前几天申请？”Agent 必须先查余额、再查制度、最后综合判断，一次模型调用做不到。
- 必讲概念：Agent Loop 的状态机本质；Observation/Action；步数预算；消息历史增长；工具结果如何回填；循环检测。
- 代码任务：实现 `run_agent(llm, tools, messages, max_steps=6)`；`Tool` 注册表；两个工具；`MockLLM` 三步脚本；每轮打印 `[step]`；返回 `AgentResult(reply, steps, trace)`；异常与最大步数处理。
- 关键图：循环图 + 消息序列图（system/user/assistant(tool_calls)/tool/assistant）。
- 练习：把最大步数改成 2 观察截断；加一个“重复调用同一工具即终止”的检测；把工具结果改成 JSON 字符串再解析。
- 衔接：循环能跑了，但工具还是硬编码的；第 03 章把工具变成可注册、可校验、可授权的能力。

### 03 | Tool Calling：把 HR 系统变成模型的手脚
- 文件：`docs/03-tool-calling.md`，代码：`code/ch03_tools.py`
- slug：`tool-calling`，order：3，minutes：60，difficulty：入门，prerequisites：["02"]
- 学习目标：
  1. 写出符合 Function Calling 规范的 JSON Schema。
  2. 用 Pydantic 做参数校验，定义统一的成功/失败返回结构。
  3. 区分读工具与写工具，给写工具加幂等键、权限校验与二次确认。
  4. 理解并行工具调用与工具结果裁剪。
- 场景：招聘 Agent 要同时查候选人、查面试官空闲时间、发面试邀请；面试邀请是外部副作用，重复发送会让候选人收到两封邮件。
- 必讲概念：Tool Schema；参数校验；错误码；幂等；读写分离；最小权限；并行调用；工具描述即 Prompt；工具太多如何路由。
- 代码任务：`@tool` 装饰器 + 注册表；`search_candidates`、`get_interviewer_slots`、`schedule_interview`（写，幂等）；Pydantic 参数模型；`ToolResult(ok, data, error, retryable)`；权限函数；`ThreadPoolExecutor` 并行只读工具；重复调用 `schedule_interview` 返回同一结果。
- 关键图：`LLM → tool_calls[] → 参数校验 → 权限 → 执行 → ToolResult → 回填`。
- 练习：新增 `create_ticket` 写工具；给 `schedule_interview` 加“面试时间必须在未来”的校验；模拟工具超时并返回可重试错误。
- 衔接：工具多了，模型需要先想清楚“先做什么、后做什么”；第 04 章讲 Planning。

### 04 | Planning：ReAct、Plan-and-Solve 与任务拆解
- 文件：`docs/04-planning.md`，代码：`code/ch04_planning.py`
- slug：`planning`，order：4，minutes：60，difficulty：进阶，prerequisites：["03"]
- 学习目标：
  1. 说清 ReAct 与 Plan-and-Solve 的区别、适用场景与成本。
  2. 让模型输出结构化计划（步骤、依赖、验收标准），再由代码执行。
  3. 在步骤失败时重规划，而不是整单重来。
  4. 识别“计划幻觉”：步骤不可执行、依赖环、缺少验收。
- 场景：HR 收到“3 周内为算法组招到 2 名 P6”的需求，需要拆成 JD、渠道、筛选、面试、offer 五步，其中面试依赖候选人筛选，offer 依赖审批。
- 必讲概念：CoT 不等于 Planning；ReAct 的 Thought/Action/Observation；Plan-and-Solve；计划 schema；依赖 DAG；重规划；反思；计划验收。
- 代码任务：同一任务跑两种模式：`react_agent` 与 `plan_and_solve`；计划 JSON 含 `steps[{id, goal, tool, depends_on, done_when}]`；拓扑执行；某步失败触发 `replan()`（MockLLM 给替代步骤）；打印两种模式的调用次数与 token。
- 关键图：ReAct 锯齿图 vs Plan-Execute-Replan 直线图；依赖 DAG。
- 练习：给计划加“预算上限”；让 replan 只重写失败步骤；比较两种模式的 token 成本。
- 衔接：计划再漂亮，入职、审批这类流程仍需确定性的状态机；第 05 章把“确定的事”交给代码。

### 05 | Workflow 与状态机：确定的事交给代码
- 文件：`docs/05-workflow.md`，代码：`code/ch05_workflow.py`
- slug：`workflow`，order：5，minutes：60，difficulty：进阶，prerequisites：["04"]
- 学习目标：
  1. 区分“该让模型决策的”和“必须由代码保证的”。
  2. 用状态、事件、守卫、动作定义入职流程。
  3. 把状态持久化到 JSON/SQLite，崩溃后能从断点恢复。
  4. 设计补偿动作与人工审批节点。
- 场景：新员工林晓 12 月 1 日入职，流程包括签合同、开账号、发设备、导师分配、试用期目标。任何一步漏掉都会导致第一天无法工作；HR 休假时流程不能卡死。
- 必讲概念：FSM（状态/事件/转移/守卫）；幂等转移；持久化；恢复；超时；补偿；人工节点；Workflow vs Agent 的边界。
- 代码任务：`OnboardingWorkflow`：`CREATED → DOCS_VERIFIED → CONTRACT_SIGNED → ACCOUNTS_READY → EQUIPMENT_READY → DAY1_READY → PROBATION`；守卫（缺离职证明不能签约）；动作（模拟开通账号）；JSON checkpoint；模拟进程崩溃后 `resume()`；拒绝非法转移。
- 关键图：状态机图 + 持久化/恢复时序图。
- 练习：增加“背调未通过 → 终止”分支；给账号开通加幂等；把 JSON 换成 SQLite 并保持接口不变。
- 衔接：流程有记忆，助手也要有记忆；第 06 章讲 Memory。

### 06 | Memory：让助手记住员工与历史
- 文件：`docs/06-memory.md`，代码：`code/ch06_memory.py`
- slug：`memory`，order：6，minutes：60，difficulty：进阶，prerequisites：["05"]
- 学习目标：
  1. 区分会话记忆、摘要记忆、长期用户记忆、业务事实记忆。
  2. 设计记忆的写入、召回、更新、遗忘与冲突处理。
  3. 用“员工画像 + 事实 + 摘要”三层结构支撑多轮对话。
  4. 知道记忆的隐私边界与租户隔离。
- 场景：员工张伟上周问过年假，今天问“那病假呢？”助手如果忘了上下文，就会重复问“你是谁、哪个部门”。但也不能把工资、病历长期记住并到处召回。
- 必讲概念：短期窗口；滚动摘要；用户画像；情景记忆/语义记忆；写入策略；召回打分；TTL；冲突（员工换部门）；隐私分级。
- 代码任务：`MemoryStore`：`window`（最近 N 轮）、`summary`（超长后压缩）、`profile`（员工 id/部门/城市/偏好）、`facts`（带来源、时间、置信度）；`recall(query)` 用关键词+时间衰减打分；冲突时新事实覆盖旧事实并保留历史；多轮对话演示“那病假呢”。
- 关键图：记忆三层结构图 + 读写流程。
- 练习：给记忆加 TTL；让摘要只保留“未完成任务”；模拟员工换部门后的冲突合并。
- 衔接：记忆越多，上下文越容易爆；第 07 章讲 Context Engineering。

### 07 | Context Engineering：上下文预算与压缩
- 文件：`docs/07-context-engineering.md`，代码：`code/ch07_context.py`
- slug：`context-engineering`，order：7，minutes：60，difficulty：进阶，prerequisites：["06"]
- 学习目标：
  1. 画出一次请求的上下文组成：系统提示、工具、记忆、知识、历史、当前问题。
  2. 做 token 预算：给每类上下文分配配额，超了按优先级裁剪。
  3. 用 map-reduce 对长面试记录做压缩，保留证据与结论。
  4. 理解“中间遗忘”（lost in the middle）与引用放置位置。
- 场景：一份 40 分钟的面试记录 6000 字，加上 5 份制度、10 轮历史，一次塞进模型会超窗口且贵；HR 只想要 5 条结论和 3 个风险点。
- 必讲概念：上下文窗口 ≠ 有效注意力；预算表；优先级；裁剪/摘要/检索三种压缩；结构化压缩；引用锚点；缓存友好排列。
- 代码任务：`ContextBuilder` 按 `system/tools/memory/knowledge/history/question` 分配预算；超限时先丢低优先级历史、再压缩知识、最后摘要；`summarize_notes()` 用 map-reduce（分段摘要 → 合并）；输出压缩前后 token 对比与保留的关键证据。
- 关键图：上下文预算饼图/条形图 + map-reduce 流程。
- 练习：把预算从 2000 调到 800 观察丢弃顺序；把关键条款放开头/中间/结尾比较；给摘要加“必须保留数字”的约束。
- 衔接：上下文里的“知识”从哪来？第 08 章进入 RAG。

---

## 第三部分 · RAG 与知识工程

### 08 | RAG 基础：从员工手册到可引用回答
- 文件：`docs/08-rag-basics.md`，代码：`code/ch08_rag_basic.py`
- slug：`rag-basics`，order：8，minutes：65，difficulty：进阶，prerequisites：["07"]
- 学习目标：
  1. 走通 RAG 全链路：解析 → 切片 → 向量化 → 索引 → 召回 → 重排 → 拼 Prompt → 引用。
  2. 手写一个哈希 Embedding 与余弦相似度，理解向量检索的本质。
  3. 让回答必须带文档编号、版本、条款，并做引用校验。
  4. 用 10 条问题算 Recall@K，知道 RAG 也要评测。
- 场景：员工问“年假没休完怎么办”，答案在 2025 版制度第 2.2 条；旧版 2024 也在库里，直接混合检索会把两个答案一起喂给模型，导致口径混乱。
- 必讲概念：RAG 解决什么问题；切片粒度；Embedding；向量库；Top-K；相似度；Rerank；引用；拒答；RAG 的失败点分类。
- 代码任务：读取 `manifest.json` 与制度文档；`chunk_markdown`；`HashingEmbedder`（字符 bigram + 哈希到 256 维）；`VectorStore`（numpy 余弦）；`retrieve(query, k)`；拼 Prompt；`MockLLM` 基于检索片段生成带引用的回答；引用校验（引用的 doc_id 必须在召回结果里）；10 条问题算 Recall@3。
- 关键图：RAG 八步流水线 + 切片对比图。
- 练习：把 chunk_size 从 400 改到 800 观察召回；增加 metadata 过滤只查 active；给引用加“必须包含条款号”。
- 衔接：基础 RAG 在真实制度库会翻车；第 09 章讲混合检索与版本治理。

### 09 | RAG 进阶：混合检索、版本治理与引用质检
- 文件：`docs/09-rag-advanced.md`，代码：`code/ch09_rag_advanced.py`
- slug：`rag-advanced`，order：9，minutes：70，difficulty：高阶，prerequisites：["08"]
- 学习目标：
  1. 实现 BM25 + 向量检索 + RRF 融合，理解为什么混合检索更稳。
  2. 用元数据过滤（状态/生效日期/部门/密级）解决版本冲突。
  3. 做增量索引、版本切换、撤销与引用质量评估。
  4. 在证据不足时拒答，而不是编造。
- 场景：2024 版年假 8 天、2025 版 10 天，知识库同时存在；远程办公还有一份 2027 讨论稿。员工问“年假几天”，系统必须只答当前有效版本，并说明依据。
- 必讲概念：稀疏 vs 稠密检索；BM25；RRF；元数据过滤；增量索引；版本与生效区间；引用质检（是否支撑结论、是否最新、是否越权）；拒答策略；知识更新流程。
- 代码任务：`BM25` 实现；`hybrid_search()` 用 RRF 融合；`filter_active()` 按状态与生效日期；增量 `upsert` 与 `delete`；比较“只向量/只 BM25/混合”在 15 条问题上的 Recall@3；引用校验 + 证据不足拒答；输出 2024/2025 对比表。
- 关键图：混合检索架构图 + 版本时间轴。
- 练习：把 RRF 的 k 改成 1/60 比较；给讨论稿加权限过滤；设计一条“制度更新”的索引重建流程。
- 衔接：制度之外，还有组织架构、技能、薪酬等结构化数据；第 10 章讲图谱与 Text2SQL。

### 10 | 知识图谱与 Text2SQL：组织、技能与数据查询
- 文件：`docs/10-knowledge-graph.md`，代码：`code/ch10_text2sql.py`
- slug：`knowledge-graph`，order：10，minutes：70，difficulty：高阶，prerequisites：["09"]
- 学习目标：
  1. 把“部门-岗位-员工-技能”建成小型知识图谱，做多跳查询。
  2. 让自然语言生成 SQL，但必须只读、白名单、自动 LIMIT。
  3. 理解 Text2SQL 的 schema linking、执行校验与结果解释。
  4. 知道 GraphRAG / Text2Cypher / Neo4j 的适用边界。
- 场景：CEO 问“技术部有多少人具备 RAG 经验？谁可以向算法组转岗？”这既要组织关系，也要技能数据；靠向量检索答不了。
- 必讲概念：Ontology；实体/关系；多跳查询；Text2SQL 流程；只读账号；SQL 注入与危险语句；schema prompt；结果校验；Text2Cypher；GraphRAG 的社区摘要。
- 代码任务：用 `org.json` + `employees.json` 建邻接表；`find_skill_paths(skill)` 做 2 跳查询；用内存 SQLite 建 `employees` 表；`nl_to_sql()` 用模板路由（count/list/avg）；`validate_sql()` 只允许 SELECT、表白名单、自动加 LIMIT；执行并格式化；演示一条被拒绝的 `DROP TABLE`；用字典模拟 Text2Cypher。
- 关键图：HR 知识图谱示例 + Text2SQL 安全闸门。
- 练习：增加“按城市统计”查询；给 SQL 加超时；把邻接表换成 Neo4j/Cypher（可选，不要求跑）。
- 衔接：能查数据不等于能上生产；第 11 章开始补可靠性。

---

## 第四部分 · 生产级可靠性

### 11 | 可靠性工程：超时、重试、幂等与降级
- 文件：`docs/11-reliability.md`，代码：`code/ch11_reliability.py`
- slug：`reliability`，order：11，minutes：70，difficulty：高阶，prerequisites：["10"]
- 学习目标：
  1. 给每个外部调用设置超时、重试、退避与抖动。
  2. 用幂等键保证重复执行不产生副作用。
  3. 用熔断、降级、补偿处理依赖故障。
  4. 设计 Agent 的终止条件，避免死循环与成本失控。
- 场景：校招季批量给 200 名候选人发面试邀请，邮件服务超时、重复点击、部分成功；如果没有幂等与补偿，会出现重复邮件、漏发、状态不一致。
- 必讲概念：失败分类（可重试/不可重试）；指数退避 + 抖动；幂等键；熔断器三态；舱壁；降级；补偿事务；超时预算；循环检测；成本上限。
- 代码任务：`FlakyEmailService`（固定随机种子，30% 失败/超时）；`retry()`；`CircuitBreaker`；`IdempotencyStore`；批量发送 20 人，部分失败后补偿；统计成功/重复/失败；演示熔断打开后快速失败与降级为“站内信”。
- 关键图：重试时间轴 + 熔断状态机 + 批量补偿流程。
- 练习：把重试次数从 3 改到 5 观察尾延迟；给幂等键加 TTL；设计“发送成功但回执丢失”的核对任务。
- 衔接：可靠性解决“别坏”，但敏感操作还需要“人签字”；第 12 章讲 HITL 与权限。

### 12 | Human-in-the-loop 与权限：敏感操作必须有人签字
- 文件：`docs/12-hitl-security.md`，代码：`code/ch12_hitl.py`
- slug：`hitl-security`，order：12，minutes：65，difficulty：高阶，prerequisites：["11"]
- 学习目标：
  1. 设计“暂停 → 人工审批 → 恢复执行”的 HITL 流程。
  2. 用 RBAC 与最小权限限制 Agent 能做什么。
  3. 对 PII 做展示脱敏，对敏感操作做双人复核。
  4. 写一条可验证的审计哈希链。
- 场景：HR 助理收到“把张伟的薪资调到 P6-1”的指令。调薪是高风险写操作，Agent 不能直接执行，必须展示依据、影响范围、审批人，并在审批后以审批人身份执行。
- 必讲概念：HITL 的价值；中断/恢复；审批单；RBAC；最小权限；职责分离；双人复核；PII 脱敏；审计日志与哈希链；不可否认性。
- 代码任务：`ApprovalGate`：敏感工具调用先创建审批单并抛出 `Interrupted`；序列化 Agent 状态；`resume(approved=True/False)`；`PermissionChecker` 校验角色；`mask_pii` 展示；审计事件哈希链 `prev_hash`；演示越权被拒、审批通过、审批拒绝、审计链校验。
- 关键图：HITL 时序图 + RBAC 矩阵 + 审计链。
- 练习：给“批量调薪”加双人复核；给审批单加过期时间；把审计日志落到 SQLite。
- 衔接：一个人忙不过来，需要多个 Agent 分工；第 13 章讲多智能体协作。

### 13 | Multi-Agent：招聘小组如何协作
- 文件：`docs/13-multi-agent.md`，代码：`code/ch13_multi_agent.py`
- slug：`multi-agent`，order：13，minutes：70，difficulty：高阶，prerequisites：["12"]
- 学习目标：
  1. 判断什么时候需要多 Agent，什么时候单 Agent 就够了。
  2. 用 Supervisor 编排招聘、面试、合规三个角色。
  3. 设计消息协议、共享状态、交接与冲突仲裁。
  4. 给多 Agent 设预算、轮次上限与终止条件。
- 场景：校招需要 simultaneously 处理 50 个候选人：招聘 Agent 筛简历，面试官 Agent 排期与评估，合规 Agent 检查竞业与隐私。三个角色目标不同，还会冲突（业务想快、合规要慢）。
- 必讲概念：角色分工 vs 工具分工；Supervisor/Peer-to-peer；消息协议；共享黑板；交接；冲突仲裁；预算；可观测性；多 Agent 的常见反模式（聊天无止境、责任不清）。
- 代码任务：`MessageBus`；`Agent` 基类；`RecruiterAgent`、`InterviewerAgent`、`ComplianceAgent`；`Supervisor` 按状态分派；共享 `CaseState`；冲突时合规一票否决；最多 12 轮；打印消息流与每 Agent token；对比单 Agent 的完成质量。
- 关键图：Supervisor 星型拓扑 + 消息时序图。
- 练习：增加“候选人拒绝 offer”分支；把 Supervisor 换成轮询；给合规 Agent 加人工升级。
- 衔接：Agent 要跑代码、跑长任务，必须隔离与可恢复；第 14 章讲 Sandbox 与长任务。

### 14 | Sandbox、Code Mode 与长任务恢复
- 文件：`docs/14-sandbox-longtask.md`，代码：`code/ch14_sandbox.py`
- slug：`sandbox-longtask`，order：14，minutes：70，difficulty：高阶，prerequisites：["13"]
- 学习目标：
  1. 理解为什么不能直接 `eval` 模型生成的代码。
  2. 用 AST 白名单实现一个最小安全计算沙箱。
  3. 用子进程 + 超时隔离不可信代码。
  4. 用 checkpoint 让 1000 份简历解析任务断点续跑。
  5. 理解 Code Mode：让模型写代码调工具，而不是一步步调工具。
- 场景：HR 要给 1000 份简历打标签并统计技能分布。逐份调用模型又慢又贵；让模型生成一段 Python 批处理代码又快又省，但代码不可信，可能删文件、读密钥、死循环。
- 必讲概念：Sandbox 边界；AST 白名单；资源限制；子进程隔离；Code Mode；长任务；checkpoint；幂等步骤；断点续跑；心跳与超时。
- 代码任务：`safe_eval()` 用 AST 只允许数字/四则/比较/列表推导；拒绝 `__import__`、属性访问、循环；`run_in_subprocess(code, timeout)` 演示超时被杀；`LongTask` 处理 50 份模拟简历，每 10 份写 checkpoint，模拟中断后 `resume()`；`code_mode_aggregate()` 让模型生成聚合代码并在沙箱执行。
- 关键图：沙箱边界图 + checkpoint 时间轴。
- 练习：给 AST 加 `sum()` 白名单；把 checkpoint 换成 SQLite；模拟代码里 `while True` 被超时终止。
- 衔接：系统能跑、能恢复，但你怎么证明它变好了？第 15 章讲可观测性与评测。

### 15 | 可观测性与评测：用数据证明 Agent 变好了
- 文件：`docs/15-observability-eval.md`，代码：`code/ch15_eval.py`
- slug：`observability-eval`，order：15，minutes：75，difficulty：高阶，prerequisites：["14"]
- 学习目标：
  1. 设计一次 Agent 运行的 Trace 与结构化日志。
  2. 定义并计算核心指标：任务成功率、工具调用准确率、引用准确率、幻觉率、P95 延迟、单任务成本。
  3. 建 Golden Case 集，做回归测试与 Replay。
  4. 用 LLM-as-judge 做主观质量评估，并知道它的偏差。
  5. 用“改动 → 评测 → 对比 → 门禁”的闭环证明优化有效。
- 场景：团队把 Prompt 改了一版，感觉“回答更好了”，但线上投诉变多。没有评测集，就无法判断是召回变差、工具调用错、还是模型胡说。
- 必讲概念：Trace/Span/Log/Metric 的区别；结构化日志字段；成功率口径；工具准确率；引用准确率；幻觉标注；Golden Set；Replay；回归门禁；LLM-as-judge 的偏差；成本/延迟分位数。
- 代码任务：跑 20 条 Golden Case；小 Agent 含检索与工具；统计 intent 准确率、工具集合准确率、must_include 命中率、P50/P95 延迟、token 成本；输出 bad case 表；对比 baseline 与 improved 两版 prompt/检索参数；设置回归门禁（成功率不得下降超过 2%）；用 MockJudge 演示打分。
- 关键图：可观测性三支柱 + 评测闭环。
- 练习：新增 5 条边界 case；把门禁改成“P95 不得高于 3s”；为 bad case 写修复方案并重跑。
- 衔接：所有能力就位，第 16 章把它们组装成一个可交付的 HR 智能服务台。

---

## 第五部分 · 项目实战与求职

### 16 | 综合项目：HR 智能服务台（Vue 3 + FastAPI）
- 文件：`docs/16-capstone.md`，代码：`app/`（本教程自带完整实现）
- slug：`capstone`，order：16，minutes：90，difficulty：项目，prerequisites：["15"]
- 学习目标：
  1. 把模糊需求拆成角色、流程、数据、接口、验收标准。
  2. 读懂并运行一个前后端完整的 HR Agent：Vue 3 工作台 + FastAPI + Agent 内核 + RAG + 审批 + 评测。
  3. 能沿着一次请求讲清 Trace：用户输入 → 意图 → 工具 → 检索 → 审批 → 回答。
  4. 能独立扩展一个新工具、一个新页面、一条新评测。
- 场景：把前面 15 章的能力装进一个 HR 共享服务中心的工作台：员工对话、引用来源、执行轨迹、待审批、评测看板。
- 必讲概念：分层架构；会话与状态；API 契约；前端交互（流式/非流式、加载、错误）；权限；部署；验收清单。
- 代码任务：阅读 `app/backend` 与 `app/frontend`；跑通 `python app/backend/main.py`；演示 6 个场景；完成 3 个扩展练习（新增“查工单”工具、加“审批历史”页、加 5 条 Golden Case）。
- 关键图：系统架构图 + 一次请求的时序图 + 数据模型。
- 练习：给工资条查询加脱敏；把 Mock 切到真实模型；用 Docker 部署。
- 衔接：项目能跑，下一步把它讲成作品集；第 17 章讲求职。

### 17 | 从教程到 Offer：作品集、面试与 90 天进阶
- 文件：`docs/17-career.md`，代码：无
- slug：`career`，order：17，minutes：50，difficulty：入门，prerequisites：["16"]
- 学习目标：
  1. 把教程项目改写成 3 条有数字、有取舍的简历 bullets。
  2. 回答 20 道高频 Agent/RAG 面试题，并能画出关键图。
  3. 用 30/60/90 天计划继续进阶。
  4. 识别“Demo 级”与“生产级”的差距，面试时主动讲风险与取舍。
- 场景：面试官问“你做的 Agent 和网上教程有什么区别？”你要能拿出评测数据、失败案例、权限与恢复设计。
- 必讲概念：STAR/STARR；指标口径；取舍叙事；系统设计题；Bad Case 复盘；作品集结构；岗位 JD 映射。
- 内容：简历模板与 3 条示例；20 道题（概念/工程/场景/行为）含答题要点；系统设计题“设计一个 HR 智能服务台”的 45 分钟答法；30/60/90 天计划；常见减分项。
- 练习：写一页项目复盘；录 3 分钟项目讲解；找同伴做一次模拟面试。
