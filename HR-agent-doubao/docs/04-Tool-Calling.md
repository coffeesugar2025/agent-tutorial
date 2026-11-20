# 04 · Tool Calling：模型选错工具，90% 是描述写糊了

## 4.1 本章目标

1. 用 `@tool` + `args_schema` 写一个"模型能选对、参数能传对"的工具；
2. 同一件事，用含糊描述 vs 合格描述，看模型的选择差别；
3. 工具报错要**回填给模型**（`ToolMessage(status="error")`），让它自己改参数；
4. 写操作要用门禁（`build_tools(allow_write)`）把权限压到工具层。

跑法：`python ch04_tools/main.py`

## 4.2 工具的三要素

```python
@tool("get_employee", args_schema=EmployeeArgs)
def get_employee(emp_id: str) -> str:
    """按工号查询在职员工的基本信息（姓名、部门、城市、职级、状态）。"""
    ...
```

模型选工具只看两样东西：**name** 和 **description**。参数靠 `args_schema` 的 JSON Schema 约束。

所以描述要写"什么时候用它"，不是"它内部做了什么"：

| 写法 | 模型的反应 |
|---|---|
| `"查信息"` + 参数名 `e` | 不知道查什么，也不知道 `e` 是什么；大概率不调，或者传字符串 `"张伟"` |
| `"按工号查询在职员工的基本信息（姓名、部门、城市、职级、状态）。"` + `emp_id` | 知道该在"问员工信息"时用，且知道要传工号 |

实测输出：

```
  含糊版 q_emp：        description='查信息'    args=['e']
  合格版 get_employee： description='按工号查询在职员工的基本信息…'  args={'emp_id': {...}}
  ★ 模型选工具只看两样：name + description。描述含糊 = 100% 调错或干脆不调
```

## 4.3 `args_schema`：把约束写进 schema，而不是写进 prompt

```python
class LeaveArgs(BaseModel):
    emp_id: str = Field(pattern=r"^E\d{5}$", description="工号，形如 E10086")
    year: int = Field(ge=2020, le=2030, description="自然年")
    leave_type: Literal["年假", "调休", "病假"] = Field(description="假期类型")
```

`pattern` / `ge` / `le` / `Literal` 会被翻译进 JSON Schema，模型看得到。这比在 prompt 里写"工号必须是 E 加五位数字"有效得多——因为它在**工具的调用契约**里，而不是在一段可能被忽略的文字里。

## 4.4 工具报错必须回填

```python
class ToolException_(...)
```

实测（这是本章最重要的一段）：

```
  问：张伟还有几天年假？
  调 {'emp_id': 'E1008', 'year': 2026, 'leave_type': '年假'}
  返回（status=error）：emp_id: String should match pattern '^E\d{5}$'
                        Please fix the error and try again.
  调 {'emp_id': 'E10086', 'year': 2026, 'leave_type': '年假'}
  返回（status=success）：E10086 2026 年年假剩余 7 天
  回答：张伟 2026 年还剩 7 天年假。
  ★ ToolMessage 带 status='error' —— 模型看得见这次失败，才有机会改
```

机制：工具抛出 `ToolException` 时，`ToolNode` 不会让整个 Agent 崩，而是把它变成一条 `ToolMessage(status="error")` 放回对话。模型下一轮就能读到"你上次参数错了，正确格式是..."。

**关键取舍**：工具内部异常要不要伪装成"成功但内容里写错误"？不要。用 `ToolMessage` 的 error 状态，模型对它的处理策略完全不同（更倾向修正）。

## 4.5 写操作门禁

```python
def build_tools(allow_write: bool) -> list:
    tools = [get_employee, get_leave_balance]
    if allow_write:
        tools.append(create_interview)
    return tools
```

实测：

```
  ① allow_write=False → 模型能看到 3 个工具，其中没有 create_interview
     回答：我目前只能查询，不能创建面试。请先在系统里走面试申请流程。
```

这就是"权限不写在 prompt 里"的做法：**不给它工具，比告诉它"别用"可靠一万倍**。真实系统里还要叠加"按角色挂载工具"和"服务端鉴权"（工具内部再查一次调用者有没有权限，不能只信 Agent）。

## 4.6 常见坑

1. **描述写成内部实现**：`"调用 SQL 查 emp 表"` —— 模型不需要知道你怎么实现，它需要知道"什么时候用"。
2. **参数名起缩写**：`e`、`n`、`d`。模型会猜错。`emp_id`、`year`、`dept` 明确得多。
3. **工具太多**：一次给 20 个工具，选择准确率断崖式下跌。按角色分组挂载（第 12 章讲）。
4. **返回值太长**：工具返回一大坨 JSON，会挤掉上下文。只回"结论 + 关键字段"，细节让模型再调一次拿（第 08 章的工具结果瘦身）。
5. **在工具里做业务决策**：工具只负责"取数/写数"，判断放外层。否则你会在工具里写出一堆 if-else 业务逻辑，改不动。

## 4.7 自检清单

- [ ] 能说出模型靠什么选工具、靠什么填参数
- [ ] 知道 `ToolException` 与 `ToolMessage(status="error")` 的关系
- [ ] 知道为什么"不给工具"比"禁止使用"更安全
- [ ] 能判断一个工具描述是好还是糊

## 4.8 练习

1. 把 `get_employee` 的 description 改成 `"查信息"`，接真模型跑 10 次，统计选错率。
2. 给 `create_interview` 加一个"面试时间必须在未来 7 天内"的校验，用 `ToolException` 抛出来，看模型怎么反应。
3. 把工具返回值从完整 JSON 改成一行摘要，对比同一问题的输出 token 数。
