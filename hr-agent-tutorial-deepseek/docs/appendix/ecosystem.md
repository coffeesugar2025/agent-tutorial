---
title: "附录 B | Agent 生态：MCP、Skill、Plugin、Harness 与选型"
slug: "ecosystem"
order: 102
minutes: 35
difficulty: "进阶"
prerequisites: ["03", "14"]
summary: "把 MCP、Skill、Plugin、Harness 放回同一张图，给出 RAG 与 Agent 框架的选型表。"
---

# 附录 B | Agent 生态：MCP、Skill、Plugin、Harness 与选型

> 第 03 章教你把函数封装成工具，第 14 章教你把代码关进沙箱。
> 这一篇回答更上层的问题：工具怎么跨应用复用？能力怎么打包分发？运行时怎么把模型、工具、沙箱、审批、评测装在一起？

## 1. 一张图看清四个概念

```text
┌─────────────────────────────────────────────────────────────┐
│ Harness（执行框架/运行时）                                   │
│  循环 · 上下文 · 工具调度 · 沙箱 · 审批 · Trace · 评测        │
│                                                             │
│   ┌──────────────┐   ┌──────────────┐   ┌───────────────┐   │
│   │ Tool         │   │ Skill        │   │ Plugin        │   │
│   │ 一个可调用函数│   │ 指令+脚本+资料│   │ 可安装的能力包 │   │
│   └──────┬───────┘   └──────┬───────┘   └──────┬────────┘   │
│          │                  │                  │            │
│          └──────────┬───────┴──────────────────┘            │
│                     ▼                                       │
│              MCP（跨应用协议）                                │
│        把工具/资源/提示词暴露给任意宿主                       │
└─────────────────────────────────────────────────────────────┘
```

- **Tool**：最小单位，一次函数调用。教程里的 `get_leave_balance` 就是 Tool。
- **Skill**：一组“怎么做某件事”的指令、脚本、参考资料，按需加载。它不是 API，更像一份可执行的操作手册。
- **Plugin**：可分发的能力包，通常包含工具、Skill、配置、权限声明，能被安装到某个宿主。
- **MCP**：让工具/资源/提示词跨宿主复用的协议。它不是 Agent 框架，也不是插件市场。
- **Harness**：把上述能力装进一个可重复运行的执行环境，负责循环、上下文、沙箱、审批、追踪与评测。

## 2. MCP：把工具从应用里解耦

### 2.1 角色与消息

MCP（Model Context Protocol）基于 JSON-RPC 2.0，分三个角色：

```text
Host（宿主，如 IDE / 桌面应用 / Agent 平台）
  │  管理多个客户端与权限
  ├─ Client A ──stdio/HTTP──► Server A（HR 只读工具）
  └─ Client B ──stdio/HTTP──► Server B（知识库检索）
```

Server 暴露三类原语：

| 原语 | 谁控制 | 例子 |
| --- | --- | --- |
| Tools | 模型决定调用 | `get_leave_balance`、`search_policy` |
| Resources | 应用/用户选择 | `policy://leave-2025`、`employee://E1001` |
| Prompts | 用户选择模板 | “生成入职清单” |

传输方式：本地进程用 `stdio`，远程服务用 Streamable HTTP（早期 SSE 已逐步退出）。工具描述、参数 Schema、返回结构都由 Server 声明，Host 负责展示与授权。

### 2.2 一个最小 Server（示意）

```python
# pip install mcp
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hr-readonly-tools")

@mcp.tool()
def get_leave_balance(employee_id: str) -> dict:
    """查询员工年假/病假余额。只读，返回脱敏字段。"""
    return {"employee_id": employee_id, "annual_remaining": 13}

if __name__ == "__main__":
    mcp.run()   # 默认 stdio
```

Host 侧配置（以桌面客户端为例）：

```json
{
  "mcpServers": {
    "hr-tools": {
      "command": "python",
      "args": ["D:/hr/mcp_server.py"]
    }
  }
}
```

### 2.3 MCP 的收益与代价

收益：

- 工具服务独立部署、独立扩缩容、独立鉴权；
- 一次实现，多个宿主复用（IDE、桌面、Agent 平台）；
- 工具描述标准化，生态可发现。

代价：

- 多一层进程/网络与协议，调试更复杂；
- 权限边界更难收：Host、Client、Server 都要校验；
- 工具投毒、混淆代理、提示注入等攻击面变大。

> ⚠️ **生产提醒**：MCP Server 不要默认信任 Host 传来的参数。`employee_id` 必须由服务端根据登录态解析，而不是让模型随便传；写操作必须走审批，不能因为“协议标准化”就放松权限。

## 3. Skill：把“怎么做”写成可加载的说明书

Skill 的典型结构：

```text
skills/leave-policy/
├─ SKILL.md              # 何时使用、步骤、边界、示例
├─ references/
│  └─ leave-2025.md      # 只读参考资料
└─ scripts/
   └─ query_balance.py   # 可选的可执行脚本
```

`SKILL.md` 的核心不是“介绍”，而是**可执行指令**：

```markdown
# 年假政策问答
## 何时使用
员工询问年假天数、结转、申请流程时。
## 步骤
1. 先调用 search_policy，过滤 status=active。
2. 引用必须包含文档编号、版本、条款。
3. 涉及个人余额时，再调用 get_leave_balance。
## 边界
证据不足时拒答；不替员工提交申请。
```

Skill 与 Tool 的区别：

| 维度 | Tool | Skill |
| --- | --- | --- |
| 本质 | 一个函数 | 一套指令 + 资料 + 脚本 |
| 谁执行 | 代码 | 模型按指令执行，可调用 Tool |
| 适合 | 确定性动作 | 流程、规范、领域知识 |
| 加载方式 | Schema 常驻 | 渐进式披露，按需读取 |

“渐进式披露”很关键：不要把所有 Skill 全文塞进系统提示，而是先给目录与触发条件，命中后再读全文。这和上下文预算是一回事。

## 4. Plugin：把能力打包分发

Plugin 通常包含：

- manifest：名称、版本、入口、权限、依赖；
- tools / skills / prompts / resources；
- 配置项与密钥引用（不落明文）；
- 安装、升级、卸载与回滚策略。

它解决的是“最后一公里”：让非开发者能安装、启用、升级能力。代价是供应链风险——一个恶意 Plugin 可能读文件、发网络请求、调用敏感工具。所以生产环境至少要有：

1. 签名与来源校验；
2. 权限清单与最小授权；
3. 安装时人工确认；
4. 运行时审计与网络出口控制；
5. 版本锁定与回滚。

## 5. Harness：Agent 的“运行底座”

Harness 不是模型，也不是某个 Prompt，而是把一次 Agent 运行所需的东西装在一起：

```text
Harness
├─ Loop：步数、终止条件、重试
├─ Context：系统提示、工具、记忆、检索、预算
├─ Tool Runtime：注册、校验、权限、幂等
├─ Sandbox：代码/命令隔离、超时、资源限制
├─ HITL：审批、中断、恢复
├─ State：会话、checkpoint、长任务
├─ Observability：Trace、日志、指标
└─ Evaluation：Golden Case、回归、Replay
```

常见实现形态：

- **DSH**：把 Agent 预设、工具、插件、沙箱、会话与评测集成在一个运行环境里；
- **OpenAI Agents SDK**：轻量 Agent/Handoff/Guardrail/Tracing；
- **LangGraph**：图状态机、checkpoint、human-in-the-loop；
- **Claude Code / Codex 类工具**：以代码与命令为中心的 Code Mode Harness。

选 Harness 时看四件事：**可观测性、恢复能力、权限模型、评测接入**。模型能力会变，底座决定你能不能安全地换模型。

## 6. RAG 与 Agent 框架选型

### 6.1 向量库 / 检索

| 工具 | 适合 | 优点 | 代价 |
| --- | --- | --- | --- |
| FAISS | 本地实验、离线批处理 | 快、轻、无需服务 | 无持久化/权限/分布式 |
| Chroma | 小团队原型 | 上手快、Python 友好 | 大规模与治理较弱 |
| Qdrant | 中小规模生产 | 过滤强、API 清晰 | 需运维 |
| Milvus | 大规模、多租户 | 生态全、可扩展 | 组件多、运维重 |
| pgvector | 已有 PostgreSQL | 事务/权限复用 | 超大规模需调优 |
| Elasticsearch | 全文 + 向量混合 | BM25 强、聚合强 | 成本高、调优复杂 |
| Pinecone | 托管、免运维 | 弹性好 | 成本、数据出境 |
| LlamaIndex | 快速搭 RAG 管线 | 连接器多 | 抽象重，需读懂内部 |

选择顺序：**先看现有基础设施**（有 PG 就 pgvector），再看规模与过滤需求，最后才看“谁的 benchmark 高”。小库上 BM25 经常不输向量，第 09 章已经实测过。

### 6.2 Agent 框架

| 框架 | 适合 | 注意 |
| --- | --- | --- |
| 手写（本教程） | 学习、可控、轻量 | 生产要自己补持久化/观测 |
| LangGraph | 状态机、长任务、HITL | 概念多，图设计要清楚 |
| LlamaIndex | RAG 为主、连接器多 | Agent 能力相对轻 |
| Dify / Coze | 低代码、快速交付 | 复杂逻辑与深度定制受限 |
| OpenAI Agents SDK | 轻量多 Agent、Tracing | 与供应商生态绑定 |

> 💡 **小白提示**：先用本教程的手写版把循环、工具、RAG、审批跑通，再看框架。否则你只是在背 API，遇到问题不知道是哪一层坏了。

## 7. 把这些能力映射到 HR 项目

| 需求 | 推荐形态 | 理由 |
| --- | --- | --- |
| 查年假余额 | Tool（或 MCP Server） | 只读、参数简单、可复用 |
| 制度问答 | Skill + RAG | 需要流程规范与引用 |
| 面试安排 | Tool + HITL | 有外部副作用，必须审批 |
| 入职流程 | Workflow / 状态机 | 步骤固定、需要恢复 |
| 多系统工具复用 | MCP | 独立部署、跨宿主 |
| 企业内分发 | Plugin | 安装、权限、升级 |
| 长任务批处理 | Harness + Sandbox + checkpoint | 隔离、恢复、可观测 |

## 8. 安全清单

- [ ] MCP Server 的参数不信任模型，身份从服务端会话取。
- [ ] 工具按读/写/敏感分级，敏感操作强制审批。
- [ ] Skill 只能读授权目录，脚本在沙箱执行。
- [ ] Plugin 有签名、权限清单、版本锁定与回滚。
- [ ] Harness 有步数/成本/时间上限，能中断与恢复。
- [ ] 所有工具调用进 Trace，敏感操作进审计链。
- [ ] 供应链依赖有清单与漏洞扫描。

> 📌 **考点**：被问“MCP 和 Function Calling 有什么区别”，一句话：Function Calling 是模型输出工具调用的能力，MCP 是让工具服务跨应用复用的协议；前者解决“怎么调”，后者解决“调谁、怎么发现、怎么复用”。
