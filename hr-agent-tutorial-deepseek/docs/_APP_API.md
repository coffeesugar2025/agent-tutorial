# 综合项目 API 契约（前后端共同遵守）

后端：FastAPI，默认 `http://127.0.0.1:8000`。前端：Vue 3 + Vite，开发时 `/api` 代理到 8000。
所有数据为虚构演示数据。默认离线 Mock 模式，不调用外部模型。

Agent 实现：LangChain 1.x / LangGraph。只读意图走 `create_agent` + `@tool`，写/敏感意图走确定性工作流 + `@tool` + 审批单；两层共享同一套权限、幂等与审计。

## 1. 目录与启动

```
app/
  backend/
    __init__.py
    main.py          # FastAPI app + 静态站点托管 + 启动入口
    config.py        # 路径、常量
    store.py         # 会话、审批、审计（内存 + 可选 JSON 落盘）
    rag.py           # 制度知识库：切片、BM25 + 向量、混合检索、引用
    tools.py         # 10 个 HR 工具 + 敏感工具标记
    agent.py         # Agent Loop、意图路由、回复生成、审批中断
    evaluation.py    # 20 条 Golden Case 评测
  frontend/          # Vue 3 + Vite
```

启动：

```powershell
python app/backend/main.py          # 8000，自动托管 app/frontend/dist（若已构建）
cd app/frontend; pnpm install; pnpm dev   # 5173，/api 代理到 8000
```

## 2. 通用约定

- 所有响应 `application/json; charset=utf-8`。
- 错误统一：`{"detail":"人类可读的错误信息"}`，HTTP 400/404/500。
- 会话 id 由前端生成（`s_` + 随机串）或后端生成；同一会话保留最近 20 条消息。
- 演示身份通过请求体的 `employee_id` 传递，不做真实认证；文档中必须注明生产环境应换成 OIDC/JWT。
- 金额单位：人民币元；薪资带宽用 `P5-2` 这种字符串。
- 时间：ISO 8601，带时区，如 `2026-12-01T14:00:00+08:00`。
- 审计日志只追加，字段包含 `actor, action, target, result, at, prev_hash, hash`。

## 3. 接口

### GET /api/health

```json
{"status":"ok","version":"1.0.0","llm_mode":"mock","chapters":18,"kb_chunks":120}
```

### GET /api/course

按 `part` 分组返回章节元数据，排除 `docs/_` 开头的内部文件。

```json
{
  "title": "HR Agent 实战教程",
  "parts": [
    {
      "id": "part-0",
      "title": "启程：从 HR 痛点理解 Agent",
      "chapters": [
        {"slug":"course-map","title":"00 | 从 HR 痛点出发：Agent 到底是什么","order":0,"minutes":40,"difficulty":"入门","summary":"..."}
      ]
    }
  ]
}
```

`part` 的五个固定值：
1. `启程：从 HR 痛点理解 Agent`
2. `单 Agent 核心`
3. `RAG 与知识工程`
4. `生产级可靠性`
5. `项目实战与求职`

### GET /api/docs/{slug}

```json
{"slug":"agent-loop","title":"02 | Agent Loop：让模型学会「再来一轮」","markdown":"---\n...","meta":{"order":2,"minutes":55,"difficulty":"入门","part":"单 Agent 核心","prerequisites":["01"],"summary":"..."}}
```

`markdown` 为原始全文（含 frontmatter），前端负责渲染。

### GET /api/scenarios

返回 8 个工作台快捷场景，字段：`id,label,message,employee_id,risk`。

至少包含：
- 查年假余额 / 年假结转规则 / 提交 3 天年假申请
- 找 Vue3 前端候选人 / 安排王浩面试（需审批）
- 把张伟薪资调到 P6-1（需审批）
- 2027 远程办公讨论稿是否生效（应拒答/提示未生效）
- 今天天气怎么样（应转人工）

### POST /api/chat

请求：

```json
{"session_id":"s_abc","message":"我还有几天年假？","employee_id":"E1001"}
```

响应：

```json
{
  "session_id": "s_abc",
  "trace_id": "8f2c1a9b3d4e",
  "reply": "你还有 **13 天** 年假（年度额度 15 天，已用 2 天）。",
  "intent": "leave_balance",
  "status": "completed",
  "steps": [
    {"index":1,"type":"llm","title":"理解问题","detail":"识别为假期余额查询","status":"ok","duration_ms":3,"data":{}},
    {"index":2,"type":"tool","title":"get_leave_balance","detail":"E1001 → 剩余 13 天","status":"ok","duration_ms":2,"data":{"annual_remaining":13}},
    {"index":3,"type":"final","title":"生成回答","detail":"附上余额明细与下一步建议","status":"ok","duration_ms":1,"data":{}}
  ],
  "citations": [],
  "usage": {"prompt_tokens":420,"completion_tokens":80,"total_tokens":500,"cost_usd":0.00033},
  "approval": null,
  "memory": {"employee":{"id":"E1001","name":"张伟","department":"技术部","city":"上海"},"facts":["本次查询：年假余额"]},
  "suggestions": ["帮我提交 3 天年假申请","年假可以结转到什么时候？"]
}
```

`status` 枚举：`completed` | `pending_approval` | `escalated` | `error`。
`steps[].type` 枚举：`llm` | `tool` | `retrieval` | `approval` | `final`。
`steps[].status`：`ok` | `error` | `pending`。

制度类回答必须返回 `citations`，每项：

```json
{"doc_id":"leave-2025","title":"年假与休假制度（2025 版）","version":"2025.1","heading":"2.2 使用与结转","snippet":"当年未休完的年假，最多可结转 5 天至次年 3 月 31 日……","score":0.83,"status":"active"}
```

敏感操作（`schedule_interview`、`adjust_salary`）不得直接执行，返回：

```json
"status": "pending_approval",
"approval": {
  "id": "ap_7f3a",
  "action": "adjust_salary",
  "summary": "将张伟（E1001）薪资带宽从 P5-2 调整为 P6-1",
  "risk": "high",
  "status": "pending",
  "payload": {"employee_id":"E1001","new_band":"P6-1"},
  "requested_by": "E1004",
  "created_at": "2026-11-15T18:30:00+08:00"
}
```

### POST /api/approvals/{approval_id}

```json
{"decision":"approve","comment":"已核对编制与带宽","approver":"E2004"}
```

响应：

```json
{"approval_id":"ap_7f3a","status":"approved","session_id":"s_abc","result":"已按 P6-1 更新张伟的薪资带宽，并写入审计日志。","audit_id":"au_9d2c"}
```

拒绝时 `status:"rejected"`，`result` 说明未执行。重复审批返回 400。
审批通过后才真正执行工具；执行失败时 `status:"failed"` 并返回原因。

### GET /api/sessions/{session_id}

```json
{"session_id":"s_abc","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}],"approval":null,"memory":{"employee":{},"facts":[]}}
```

### GET /api/kb/search?q=年假&top_k=5&include_archived=false

```json
{"query":"年假","results":[{"doc_id":"leave-2025","title":"年假与休假制度（2025 版）","version":"2025.1","heading":"2.1 年假天数","snippet":"...","score":0.81,"status":"active"}]}
```

### POST /api/eval/run

```json
{
  "summary": {"total":20,"passed":18,"success_rate":0.9,"tool_accuracy":0.95,"citation_accuracy":0.92,"avg_latency_ms":42,"p95_latency_ms":88,"total_tokens":12000,"cost_usd":0.006},
  "baseline": {"success_rate":0.85,"tool_accuracy":0.9,"p95_latency_ms":95},
  "cases": [
    {"id":"G01","input":"我还有几天年假？","passed":true,"intent_ok":true,"tools_ok":true,"must_include_ok":true,"latency_ms":12,"tokens":480,"reply":"...","failures":[]}
  ]
}
```

评测必须确定、快速（< 5 秒）、不依赖网络；允许 1–3 条真实失败案例用于教学，但失败原因要稳定。

## 4. 意图与工具（后端实现依据）

意图：`leave_balance`、`leave_policy`、`apply_leave`、`candidate_search`、`candidate_query`、`interview_schedule`、`salary_adjust`、`onboarding`、`ticket_query`、`out_of_scope`。

工具（只读/写/敏感）：

| 工具 | 类型 | 说明 |
| --- | --- | --- |
| `get_leave_balance` | 读 | 查年假/病假余额 |
| `search_policy` | 读 | 制度混合检索，带引用 |
| `check_leave_eligibility` | 读 | 校验余额、提前天数、冲突 |
| `submit_leave_request` | 写 | 幂等提交请假 |
| `search_candidates` | 读 | 按技能/年限筛候选人 |
| `get_candidate` | 读 | 候选人详情（联系方式脱敏） |
| `schedule_interview` | 敏感写 | 创建面试日程，必须审批 |
| `adjust_salary` | 敏感写 | 调整薪资带宽，必须审批 |
| `start_onboarding` | 写 | 启动入职状态机 |
| `get_ticket` | 读 | 查工单详情 |

回复要求：
- 余额类给数字 + 年度额度 + 已用；不要只贴 JSON。
- 制度类必须给“根据《…》（版本）第…条”并附引用；检索不到时明确说“制度库中没有找到依据，建议转人工”，不得编造。
- 写操作给单号/状态；敏感操作说明“已提交审批，审批通过后才会执行”。
- 边界类统一“这个问题超出我的服务范围，已为你转人工（工单号…）”。
- 每次回复后给 2 条 `suggestions`。

## 5. 前端页面

路由：

- `/`：课程首页。品牌「HR Agent 学堂」，hero、技术栈徽章、学习路径、章节卡片、进度。
- `/learn/:slug`：章节阅读。左侧章节目录（按 part 分组），中间 Markdown，右侧本页目录；上一章/下一章；标记完成（localStorage）。
- `/playground`：HR Agent 工作台。左聊天、右四个 Tab：执行轨迹、引用来源、记忆、待审批；顶部选择演示身份（张伟 E1001 / 赵敏 E1004 HR / 郑爽 E1010 招聘）。
- `/eval`：评测看板。指标卡、运行按钮、用例表、Bad Case 区。
- 404。

设计：
- 中文界面；浅色主题；主色 `#4f46e5`，背景 `#f7f7fb`，正文 `#1f2430`；圆角 12–16px；细边框；轻阴影。
- 字体：`-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`；正文 16px，行高 1.8。
- 桌面三栏，移动端单栏 + 抽屉；按钮、输入框、Tab 都要有 hover/focus 状态。
- Markdown：标题锚点、代码高亮 + 复制按钮、表格、引用块（三种 callout 着色）、`<details>` 正常展开。
- 不引入大型 UI 库；图标用内联 SVG 或字符。
- 所有网络失败要有可见错误提示与重试按钮，不能白屏。
