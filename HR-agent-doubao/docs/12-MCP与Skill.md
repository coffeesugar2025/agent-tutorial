# 12 · MCP / Skill / Plugin：工具的"插座标准"

## 12.1 三个词先分清（面试高频）

| 概念 | 是什么 | 解决什么 |
|---|---|---|
| **Tool** | 一个函数（`@tool`） | 模型能调它 |
| **MCP** | 跨进程/跨语言的**工具协议**（JSON-RPC） | 工具装在别人的服务里，也能被你的 Agent 调 |
| **Skill / Plugin** | 一份"能力包"（工具 + 提示词 + 使用规范 + 触发条件） | 把"专家怎么做这件事"固化下来 |

跑法：`python ch12_mcp/main.py`

## 12.2 MCP 只规定三件事

```python
class MockMCPServer:
    def handle(self, method, params) -> dict:
        if method == "tools/list":  return {"tools": [...]}
        if method == "tools/call":  return {"content": [{"type": "text", "text": "..."}]}
```

1. **怎么发现工具**（`tools/list`，返回 name + description + inputSchema）
2. **怎么调用**（`tools/call`，传 name + arguments，返回 content 数组）
3. **怎么报错**（`isError: true` + 错误文本）

它**不规定**工具内部业务逻辑——这正是它能跨厂商通用的原因。

实测：

```
  服务名：hr-tools
    - get_leave_balance: 查询员工某年度某类假期余额
    - get_headcount: 按部门查询在职人数（聚合口径）
  tools/call → 技术中心 在职 3 人
```

## 12.3 适配层：JSON Schema → LangChain Tool

这是 MCP 接入的唯一技术活：

```python
def mcp_tool_to_langchain(client, spec):
    # ① JSON Schema 的 properties → pydantic 字段
    fields = {k: (TYPE_MAP.get(v.get("type","string"), str), ... if k in required else None)
              for k, v in spec["inputSchema"]["properties"].items()}
    args_model = create_model(f"{spec['name']}_args", **fields)

    # ② 调用时把结果转成字符串（模型只认字符串）
    def _call(**kwargs):
        out = client.handle("tools/call", {"name": spec["name"], "arguments": kwargs})
        if out.get("isError"): raise ValueError(out["content"][0]["text"])
        return "\n".join(c.get("text","") for c in out["content"])

    return StructuredTool.from_function(func=_call, name=spec["name"],
                                        description=spec["description"], args_schema=args_model)
```

生产上这一步由 `langchain-mcp-adapters` 的 `load_mcp_tools()` 完成。但**你要知道它做了什么**，否则工具参数对不上时无从排查。

跑通：

```
  工具往返 2 次
  最终回答：技术中心在职 3 人；张伟 2026 年年假剩 7 天。
```

## 12.4 接真 MCP 的标准写法

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

async with MultiServerMCPClient({
    "hr": {"command": "python", "args": ["ch12_mcp/server.py"], "transport": "stdio"},
    "fs": {"url": "http://localhost:8000/mcp", "transport": "streamable_http"},
}) as client:
    tools = await client.get_tools()
    agent = create_react_agent(model, tools)
    await agent.ainvoke({"messages": [("user", "查一下张伟的年假")]})
```

需要 `pip install langchain-mcp-adapters mcp`。本章的 `ch12_mcp/server.py` 是一个可跑的 stdio 服务端样例。

## 12.5 MCP 落地的四个现实问题

1. **工具太多 → 模型选错**：一个服务可能一次给十几个工具。解法：**按角色分组挂载**（HR 助手只挂 hr 服务），别全塞。
2. **权限不在你这侧**：MCP 服务自己要按调用者身份鉴权，不能只靠 Agent 的 prompt。传 `user_id` 进 params 是最基本的做法。
3. **网络抖动**：MCP 走本地 stdio 还好，走 HTTP 必须加超时与降级（第 15 章）。
4. **结果格式不统一**：有的返回 JSON 字符串，有的返回 markdown。适配层统一转成"结论 + 关键字段"，别让模型猜。

## 12.6 Skill：写"什么时候用"，比写工具更重要

一份 Skill 至少包含四部分：

```markdown
# 离职办理 Skill
## 触发条件       员工提出离职 / HR 发起离职流程
## 前置检查       合同类型、试用期状态、是否有竞业协议
## 步骤           ① 确认离职类型 ② 计算最后工作日 ③ 走审批 ④ 交接 ⑤ 结算
## 禁止事项       不得口头承诺补偿金额；不得跳过交接
```

★ **写 Skill 的关键不是写工具，是写"什么时候用、按什么顺序用、什么情况下不许用"。** 这也是它和 Tool 的本质区别：Tool 是能力，Skill 是纪律。

## 12.7 常见坑

1. **`@tool(name)` 用在动态函数上**：会报 `Function must have a docstring if description not provided`。动态生成的工具要用 `StructuredTool.from_function`，显式传 `name` / `description` / `args_schema`。
2. **JSON Schema 的 `required` 漏处理**：全设成可选，模型会省参数。
3. **把 MCP 当"遥测"用**：MCP 不保证顺序、不保证幂等，写操作要自己加幂等键。
4. **一个 Agent 挂 30 个工具**：选择准确率崩。分组。

## 12.8 自检清单

- [ ] 能说出 Tool / MCP / Skill 的区别
- [ ] 知道 MCP 的三步握手
- [ ] 能解释适配层做了哪两件事
- [ ] 理解"工具太多"为什么要分组

## 12.9 练习

1. 给 `MockMCPServer` 加一个写工具 `create_interview`，用 `allow_write` 门禁控制。
2. 装 `langchain-mcp-adapters`，真跑 `server.py`，对比 `load_mcp_tools` 与自己适配的差异。
3. 写一份"入职办理" Skill，把 6 步流程、每步工具、禁止事项写全，再让 Agent 按它执行。
