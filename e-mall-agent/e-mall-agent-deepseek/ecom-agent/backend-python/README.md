# 星图商城 · 电商智能体后端（Python）

FastAPI + LangChain 1.5 + SQLAlchemy 2.x + Milvus/MySQL/Redis/RabbitMQ 的电商智能体服务，
覆盖 SUPERVISOR / SHOPPING / SERVICE / OPS 四类 Agent、混合检索（dense + sparse + RRF + rerank）、
HITL 人工审批、可观测性，以及**离线评测、MCP 网关、Skill 渐进式披露**。

> 关键设计：`MOCK_LLM=true` + `EMBEDDING_PROVIDER=hash` + `VECTOR_STORE=memory` 时，
> 整条链路（对话 / 检索 / 工具 / 评测 / 测试）**完全离线可跑**，不需要任何 API Key 或中间件。

---

## 1. 目录结构

```
backend-python/
├── app/
│   ├── api/                # REST 路由（/api/v1）
│   ├── agents/             # Agent 运行时（路由 / 工具循环 / 终止条件）
│   ├── common/             # 信封、错误码、ID、token 估算、时间
│   ├── eval/               # ★ 评测：dataset / judge / runner
│   ├── hitl/               # 人工审批
│   ├── infra/              # DB / Redis / RabbitMQ / Milvus / ORM 模型
│   ├── llm/                # 多供应商 + 熔断 fallback + 成本
│   ├── mcp/                # ★ MCP 网关（stdio + HTTP JSON 降级）
│   ├── memory/             # 会话 / 长期记忆
│   ├── mq/                 # 消息消费者
│   ├── obs/                # 日志 / 指标 / Trace
│   ├── rag/                # 切片 / 向量化 / 混合检索 / 入库 / 检索评估
│   ├── security/           # 认证 / RBAC / 注入防护 / PII / 限流
│   ├── skills/             # ★ Skill 渐进式披露（builtin/ 内置技能）
│   ├── tools/              # 12 个工具 + 注册表 + 执行器
│   ├── config.py
│   └── main.py
├── eval_data/              # ★ shopping / service / rag 三个评测集（各 10 条）
├── scripts/
│   ├── run_eval.py         # ★ 评测 CLI
│   └── seed_demo.py        # ★ 演示数据 + 知识索引
├── tests/
│   ├── conftest.py         # ★ 零外部依赖夹具
│   ├── unit/               # 单元测试
│   └── integration/        # 检索/评测集成测试
├── requirements.txt / requirements-dev.txt
└── pyproject.toml          # black / ruff / pytest 配置
```

---

## 2. 快速开始

```powershell
cd backend-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

copy .env.example .env      # Linux/macOS: cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2.1 完全离线（推荐首次体验 / CI）

```powershell
$env:MOCK_LLM="true"
$env:EMBEDDING_PROVIDER="hash"
$env:VECTOR_STORE="memory"
$env:MQ_ENABLED="false"
$env:DATABASE_URL="sqlite:///./var/demo.db"
$env:AUTO_CREATE_TABLES="true"

python scripts/seed_demo.py        # 用户/商品/订单/物流/知识库（含索引）
python scripts/run_eval.py --asker mock --repeat 3
python -m pytest
```

`seed_demo.py` 写入的演示账号：`demo` / `agent` / `admin`，统一口令 `Passw0rd!`
（`security` 模块依赖不可用时脚本会退化为占位哈希，仅影响登录，不影响业务数据）。

### 2.2 接真实依赖

| 依赖 | 变量 | 不可用时的行为 |
|---|---|---|
| MySQL | `MYSQL_*` 或 `DATABASE_URL` | 服务启动失败（生产必需） |
| Redis | `REDIS_HOST` | 降级为进程内状态，日志告警 |
| RabbitMQ | `MQ_ENABLED=false` | 异步任务落 `async_task` 表由本地 drainer 消费 |
| Milvus | `VECTOR_STORE=memory` | 自动降级内存向量库 + 关键词检索 |
| LLM | `MOCK_LLM=true` | 确定性 Mock 模型 |
| Embedding | `EMBEDDING_PROVIDER=hash` | 本地哈希向量 |

---

## 3. 评测模块（`app/eval`）

### 3.1 数据格式（`eval_data/*.jsonl`）

每行一个 JSON，空行与 `#` 注释会被忽略：

```json
{"id":"s-001","suite":"shopping","question":"帮我推荐几款 3000 元以内的拍照手机",
 "expected":"在 3000 元预算内，推荐小米 14……",
 "checks":[{"type":"contains","value":"3000"},{"type":"regex","value":"小米"}],
 "maxSteps":6}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 文件内唯一（重复会报错并给出首次出现的行号） |
| `suite` | — | 缺省取文件名（`rag.jsonl` → `rag`） |
| `question` | ✅ | 用户问题 |
| `expected` | — | 参考答案 / 期望要点（LLM judge 与 mock 判分的依据） |
| `checks` | — | 规则断言；为空表示交给 LLM judge |
| `maxSteps` | — | 该用例允许的最大步数（默认 6） |

`checks` 支持三种类型（白名单校验，未知类型直接加载失败）：

| type | 含义 | 示例 |
|---|---|---|
| `contains` | 回答必须包含子串（忽略大小写） | `{"type":"contains","value":"买家承担"}` |
| `not_contains` | 回答不得出现该内容 | `{"type":"not_contains","value":"已退款成功"}` |
| `regex` | 正则必须匹配（`IGNORECASE + DOTALL`） | `{"type":"regex","value":"iPhone\\s*16"}` |

三个内置评测集：

| suite | 用例数 | 覆盖点 | 规则 / LLM judge |
|---|---|---|---|
| `shopping` | 10 | 预算/品牌推荐、对比、库存、以旧换新、无货诚实拒答 | 9 / 1 |
| `service` | 10 | 订单、物流、退款资格/时效、审批、生鲜、发票、投诉转人工 | 9 / 1 |
| `rag` | 10 | 运费归属、七天无理由、退款时效、保修、价保、会员、定制商品 | 8 / 2 |

### 3.2 判定（`app/eval/judge.py`）

```
有 checks ──► 规则断言（全部通过才算通过，score = 通过率）
无 checks ──► LLM judge（rubric 四维加权）
                 ├─ MOCK_LLM=true / --judge mock ──► 确定性启发式（同输入同分）
                 └─ LLM 调用失败 ──► 同样降级确定性启发式（mode=heuristic-fallback）
```

内置 rubric（权重和 100%）：

| 维度 | 权重 | 关注点 |
|---|---|---|
| relevance | 30% | 是否直接回应用户问题 |
| accuracy | 30% | 政策/价格/订单事实是否准确 |
| completeness | 25% | 是否覆盖关键步骤、边界与后续操作 |
| safety | 15% | 无越权承诺、无 PII、未执行需审批操作 |

分数统一由 `normalize_score()` 归一到 `[0,1]`：兼容 1 / 10 / 100 分制，
`NaN`/`inf`/非数字一律 0，通过线默认 `0.6`（`PASS_THRESHOLD`）。
LLM 判定使用 `LLMClient.structured` + `TaskClass.JUDGE`（fast 档），失败不阻断评测。

### 3.3 pass@k 与 pass^k

`repeat=k` 表示同一用例跑 k 次：

| 指标 | 定义 | 含义 |
|---|---|---|
| **pass@k** | k 次中**至少一次**通过（`any`） | 能不能做对 |
| **pass^k** | k 次**全部**通过（`all`） | 稳不稳定 |
| attempt pass rate | 通过次数 / 总次数 | 整体成功率 |

落库映射（`eval_run`）：

| 列 | 写入内容 |
|---|---|
| `total` / `passed` / `pass_rate` | 按 **attempt** 统计（10 用例 × 3 次 → 30） |
| `pass_k` | **pass^k**（全部 k 次都通过的比例） |
| `repeat_times` | k |
| `avg_cost_cents` / `avg_latency_ms` | 按用例平均的成本（分）/ 延迟（ms） |
| `report` | 完整报告 JSON，含 `passAtK`、`passHatK`、每用例每次尝试 |

`eval_case_result` 每个用例一行：`passed` 取 pass@k、`score` 取最佳分、`attempts`=k、
`actual` 为最佳回答、`detail` 为逐次尝试明细。

### 3.4 评测 CLI（`scripts/run_eval.py`）

```powershell
# 数据概览
python scripts/run_eval.py --list

# 离线自检（Mock 回答 + 确定性裁判，不写库不联网）
$env:MOCK_LLM="true"; python scripts/run_eval.py --asker mock

# 指定 suite、k=3，并落库（SQLite 自动建表）
$env:DATABASE_URL="sqlite:///./var/eval.db"; $env:AUTO_CREATE_TABLES="true"
python scripts/run_eval.py --suite shopping service --repeat 3 --persist

# CI 用法：JSON 输出 + 通过率门槛（不达标退出码 1）
python scripts/run_eval.py --asker mock --json --min-pass-rate 0.8
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--suite a b` | 全部 | 要跑的 suite |
| `--data-dir` | `EVAL_SUITES_DIR`（`eval_data`） | 数据目录 |
| `--repeat` | 1 | 每个用例重复次数 k |
| `--asker` | `auto` | `auto` 尝试接入 `app.agents.*`，失败降级 `mock` |
| `--judge` | `auto` | `auto/rules/mock/llm`（有 checks 的用例始终走规则） |
| `--threshold` | 0.6 | 判分通过线 |
| `--limit` / `--concurrency` | — / 1 | 限流与并发 |
| `--persist` | 关 | 写 `eval_run` / `eval_case_result` |
| `--json` | 关 | JSON 输出（便于 CI 解析） |
| `--min-pass-rate` | 0.0 | 每个 suite 的 pass@k 下限 |

退出码：`0` 达标，`1` 未达标，`2` 无/非法评测数据。

> `--asker auto` 会在 `app.agents.runtime/pipeline/graph/supervisor/team` 中查找
> `ask / ask_once / answer_question / answer / run_agent / execute` 入口，
> 找不到就用确定性 mock（回显 `expected`），因此评测链路不依赖 Agent 是否已实现。

---

## 4. MCP 网关（`app/mcp/server.py`）

把 `app/tools/registry.py` 的 12 个工具暴露给外部 Agent 运行时，支持两种形态：

| 形态 | 触发条件 | 说明 |
|---|---|---|
| MCP stdio | 安装官方 `mcp` SDK | `python -m app.mcp.server` 启动，工具 schema 复用 registry |
| HTTP JSON | 缺 SDK 或需要调试 | `GET /mcp/tools` 返回 JSON 描述（`degraded=true`） |

挂载到主应用（新增路由，不改动既有 `main.py` 之外的代码）：

```python
from app.mcp.server import mount as mount_mcp

mount_mcp(app)   # 暴露 /mcp/tools、/mcp/info、/mcp/health、/mcp/tools/{name}/call
```

> 说明：本模块已自测（`TestClient` 覆盖），但 `app/main.py` 属于既有文件，
> 按"只新增不改动"的约束未自动挂载；上线时补上面一行即可。

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/mcp/tools` | 工具清单（name / description / inputSchema / annotations / risk） |
| GET | `/mcp/info` | 服务名、版本、协议版本、传输方式、是否降级 |
| GET | `/mcp/health` | 健康检查 |
| POST | `/mcp/tools/{name}/call` | 调用工具，body `{"arguments": {...}}` |

```powershell
curl http://127.0.0.1:8000/mcp/tools
curl -X POST http://127.0.0.1:8000/mcp/tools/search_products/call `
     -H "Content-Type: application/json" `
     -d '{"arguments": {"query": "降噪耳机", "topK": 3}}'
```

安全约定：

* 默认**只读**：`WRITE` / `IRREVERSIBLE` 工具一律拒绝，必须走应用内 HITL 审批链路；
* `IRREVERSIBLE` 即使显式放开也只会返回 `approvalRequired`，不会自动执行；
* 工具结果沿用 `ToolResult.to_content()`（含 PII 脱敏 + 外部数据隔离）；
* stdio 模式可用 `MCP_ALLOW_WRITE=true` 放开 `WRITE`（不推荐）。

降级保证：模块顶层只 import 标准库，`mcp` / `fastapi` 懒加载；缺依赖时
`build_server()` 返回 `None`、`create_router()` 返回 `None`，不会 import 失败。

---

## 5. Skill 渐进式披露（`app/skills`）

三层披露控制 prompt 成本：

| 层 | API | 内容 |
|---|---|---|
| L1 metadata | `loader.discover()` / `list_skills()` / `index_block()` | frontmatter：name/description/tags/triggers/allowedTools/maxSteps |
| L2 body | `loader.load_body(name)` / `get(name, load_body=True)` | Markdown 正文（执行步骤、话术、禁止事项） |
| L3 resources | `loader.list_resources()` / `read_resource()` | 同目录模板/表格，带目录穿越防护与大小上限 |

内置技能：

| Skill | 场景 | 允许工具 |
|---|---|---|
| `refund-policy` | 退款/退货资格、运费、时效、例外品类 | `search_knowledge` `get_order` `check_refund_eligibility` `escalate_to_human` |
| `product-compare` | 商品对比、预算/品牌导购 | `search_products` `get_product_detail` `compare_products` `search_knowledge` |

`SKILL.md` 模板：

```markdown
---
name: my-skill
description: 一句话说明何时使用
version: 1.0.0
tags: [service]
triggers: [退款, 运费]
allowedTools: [search_knowledge, get_order]
maxSteps: 6
---

# 标题
## 何时启用
## 执行步骤
## 回答模板
## 禁止事项
```

运行时用法：

```python
from app.skills.loader import get_loader

loader = get_loader()
loader.index_block()                                   # L1：注入 system prompt
loader.match("退货运费谁承担")                          # 按 triggers 命中
loader.prompt_block(["refund-policy"], include_body=True)  # L2：按需带正文
loader.read_resource("refund-policy", "resources/faq.md")  # L3：资源
```

* 自定义目录：`SKILLS_DIR=/path/to/skills`（默认 `app/skills/builtin`）；
* frontmatter 解析优先 `PyYAML`，缺失时用内置解析器（`key: value`、`[a, b]`、`- item`）；
* 目录不存在 / 单个技能损坏只记日志并跳过，不影响其它技能与服务启动。

---

## 6. 演示数据（`scripts/seed_demo.py`）

```powershell
# SQLite + 内存向量库（零依赖）
$env:DATABASE_URL="sqlite:///./var/demo.db"; $env:VECTOR_STORE="memory"
python scripts/seed_demo.py

# 只灌业务数据 / 强制重建索引 / 纯 JSON 输出
python scripts/seed_demo.py --skip-knowledge
python scripts/seed_demo.py --force-reindex
python scripts/seed_demo.py --json
```

内容与特性：

* 3 个账号（demo/agent/admin）、4 个类目、10 件商品、4 笔订单（覆盖运输中/已签收 2 天/已完成 10 天/待发货大额）、2 条物流轨迹；
* 4 篇知识文档（退款政策、以旧换新规则、售后服务手册、FAQ），通过 `app.rag.ingest.ingest_text` 切片 + 向量化 + 建索引；
* **幂等**：用户/商品按唯一键 upsert，订单按订单号 upsert，知识文档按标题复用（已索引则 skipped）；
* 默认读 `DATABASE_URL`（SQLite/MySQL 均可），`--database-url` 可临时覆盖。

---

## 7. 测试

```powershell
python -m pytest                 # 全量（92 个用例）
python -m pytest -m unit         # 纯逻辑
python -m pytest -m integration  # 需要 SQLite 的检索/评测链路
python -m pytest tests/unit/test_chunker.py -v
```

零外部依赖（`tests/conftest.py`）：

* 导入 `app.*` **之前**设置 `MOCK_LLM=true`、`EMBEDDING_PROVIDER=hash`、
  `VECTOR_STORE=memory`、`MQ_ENABLED=false`、`DATABASE_URL=sqlite:///./test.db`；
* 清理 `get_settings` 缓存、embedding 单例、内存向量库，并清空知识/幂等/审计/评测临时表；
* 会话结束 `drop_all` + 删除 `test.db`。

覆盖点：

| 测试文件 | 用例 | 覆盖 |
|---|---|---|
| `unit/test_chunker.py` | 7 | 清洗、空文档、size/overlap 边界、父块包含关系、无分隔符硬切、统计 |
| `unit/test_sparse.py` | 8 | 中英分词、bigram/单字、hash id 稳定、L2 归一、点积/余弦、覆盖率、编码器 |
| `unit/test_embedding_hash.py` | 6 | 确定性、L2 归一、相似文本排序、空文本、维度下限、单例重置 |
| `unit/test_tokens.py` | 8 | CJK/ASCII 估算、混合文本、截断预算、fit_texts、消息开销、成本折算 |
| `unit/test_rrf.py` | 6 | RRF 公式、k 参数、双路去重排序、dense payload 优先、空输入、单路保序 |
| `unit/test_injection.py` | 8 | 直接/间接注入、中英文、零宽字符、弱信号 SUSPICIOUS、标签/角色中和、隔离包装 |
| `unit/test_pii.py` | 8 | 手机/身份证/银行卡/邮箱/地址/姓名、混合文本、递归对象、空输入 |
| `unit/test_cost.py` | 7 | 百万 token 单价、缓存折扣、最低 1 分、usage 提取/估算、mock 免费、落库 |
| `unit/test_idempotency.py` | 7 | 幂等键稳定性、WRITE 二次命中缓存、不同参数不缓存、READ 不去重、IRREVERSIBLE 审批、审计、参数校验 |
| `unit/test_eval_pipeline.py`（额外） | 9 | 数据集一致性、分数归一、规则/LLM judge 分流、mock 确定分、pass@k/pass^k、落库字段 |
| `unit/test_skills_mcp.py`（额外） | 11 | Skill L1/L2、triggers 匹配、目录穿越、缺目录降级、MCP schema/注解、只读拦截、无 SDK 降级、HTTP 路由 |
| `integration/test_retrieval_eval.py` | 7 | 入库切片、重复索引幂等、混合检索命中、recall/nDCG/MRR、上下文组装预算、关键词降级 |

---

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| `test.db` 残留 / 测试互相污染 | 删除 `backend-python/test.db` 后重跑；夹具已在会话结束清理 |
| 评测 `persist_error` | 检查 `DATABASE_URL`；SQLite 需 `AUTO_CREATE_TABLES=true`，MySQL 先执行 `deploy/mysql/init` |
| 评测 LLM judge 全部降级 | 无 API Key 时设置 `MOCK_LLM=true`（确定性裁判），或配置 `DEEPSEEK_API_KEY` |
| `GET /mcp/tools` 404 | 主应用尚未挂载：加 `from app.mcp.server import mount; mount(app)` |
| `python -m app.mcp.server` 卡住 | 正常：stdio 模式在等 MCP 客户端；只想看工具清单用 `GET /mcp/tools` 或 `python -c "from app.mcp.server import tools_payload; ..."` |
| Skill 未生效 | 检查 `SKILLS_DIR`、`SKILL.md` frontmatter 格式，`loader.reload()` 热更新 |
| seed 后登录失败 | `security` 依赖（passlib/bcrypt）缺失时退化为占位哈希；安装依赖后重跑 seed |
