# 16 · 长任务：断点续跑、分批、沙箱、预算

## 16.1 本章目标

一个"跑一晚上"的任务必须回答四个问题：

| 问题 | 本章做法 |
|---|---|
| 跑到一半崩了，从哪继续？ | checkpoint 文件 + 幂等键 |
| 一次塞 500 份简历会爆吗？ | 分批 + 批间隔 + 每批上限 |
| 模型写的代码能直接执行吗？ | 沙箱：禁项、限额、真隔离 |
| 花多少钱？ | 预算闸门，超了就停并保留现场 |

跑法：`python ch16_long_task/main.py`

## 16.2 断点续跑的粒度

```python
def save_ckpt(ck): CKPT.write_text(json.dumps(ck, ensure_ascii=False, indent=2), encoding="utf-8")

for bi in range(ck["batch"], total_batches):
    for r in batch:
        if r["id"] in ck["done"]: continue      # ← 幂等：重跑不重复写
        ...
        ck["done"].append(r["id"])
        save_ckpt(ck)                            # ← 每条落盘
    ck["batch"] = bi + 1
    save_ckpt(ck)
```

★ **粒度决定代价**：每批落盘 → 崩了最多丢一批；每条落盘 → 最多丢一条。500 条任务每条落盘，IO 是能接受的；每条都写数据库事务就要想清楚。

实测：

```
  上次进度：已完成 0 份，第 0 批之后中断
  第 1 批（4 份）：
    C1001 年限 3 → 82 分（累计 60 tokens）
    ...
  第 3 批（4 份）：
    C10011 年限 3 → 65 分（累计 660 tokens）
    ⛔ 预算闸门：已用 660 tokens > 600，停止并保留现场
```

注意最后一个成功的是 C10011，C10012 还没跑——**checkpoint 保留了现场**，下次从 C10012 继续。

## 16.3 分批与退避

```python
BATCH = 4
time.sleep(0.2)     # 批间退避：给下游喘息，也避免触发限流
```

三个经验值：

- 批量大小按"下游能承受的 QPS"定，不是按"想跑多快"定；
- 批间必须 sleep（哪怕 200ms），否则 4 个并发就能把小系统打挂；
- **失败单条重试，不要整批回滚**。整批回滚会让你永远跑不完那批里的毒丸数据。

## 16.4 沙箱：字符串黑名单只是第一道闸

```python
FORBIDDEN = ("import", "open", "exec", "eval", "__", "subprocess", "os.", "socket")

def sandbox(code, max_chars=2000):
    if len(code) > max_chars: return "⛔ 代码过长"
    for bad in FORBIDDEN:
        if bad in code: return f"⛔ 命中禁止项：{bad}"
    exec(compile(code, ...), {"__builtins__": {...白名单...}}, {})
```

实测：

```
  ① 正常计算：✅ 执行完成
  ② 读文件：⛔ 命中禁止项：open
  ③ 偷环境：⛔ 命中禁止项：import
  ④ 死循环：⛔ 运行失败…（真沙箱靠超时杀掉，不是靠字符串检查）
```

★ **不要用字符串黑名单冒充沙箱。** 生产做法：

| 手段 | 具体 |
|---|---|
| 隔离 | Docker（gVisor）/ Firecracker / 微虚拟机（E2B） |
| 网络 | 无网络（这是最重要的一条） |
| 资源 | CPU / 内存 / 磁盘限额，进程级超时 |
| 文件 | 只挂一个临时目录，跑完销毁 |
| 权限 | 非 root、无 docker socket |

demo 的 `exec` 沙箱只够演示"四道闸的思路"，一行 `().__class__.__bases__` 就能绕过。

**Code Mode 的正确姿势**：让模型写代码，但代码在容器里执行，结果只回传 stdout 的摘要。这样既利用了模型的代码能力，又不用信任它。

## 16.5 预算闸门

```python
if ck["spent_tokens"] > BUDGET_TOKENS:
    save_ckpt(ck)
    raise SystemExit(0)
```

三个要点：

1. **闸门要检查在"做之前"**，不是做完才发现超了；
2. **超了要保留现场**（checkpoint 已存），供人工接手；
3. **预算要有三个维度**：token、时长、金额。任何一个超都停。

## 16.6 LangGraph 版本（长任务的正规做法）

本章用文件做 checkpoint 是为了讲清"最小可行"。真项目用 LangGraph 的 checkpointer + `Send` 分批：

```python
graph = builder.compile(checkpointer=SqliteSaver.from_conn_string("long.db"))
graph.invoke(input, config={"configurable": {"thread_id": "batch-2026-11-15"}})
```

好处：状态自动落库、可随时 resume、可配合 `interrupt()` 做"跑到一半停下来问人"（第 14 章）。

## 16.7 常见坑

1. **checkpoint 只存"完成列表"不存"中间结果"**：续跑时要重算前面的。存 `{id: result}` 而不是 `[id]`。
2. **`save_ckpt` 并发写**：多线程/多进程同时写同一个 json，会写坏。用临时文件 + 原子 rename，或换 sqlite。
3. **毒丸数据**：某一条永远失败，整批卡住。要有"失败 N 次就跳过并记录"。
4. **沙箱里能联网**：模型写的代码把数据传出去，一次事故。
5. **预算只算 token 不算重试**：重试 3 次就是 3 倍成本，别忘了算。

## 16.8 自检清单

- [ ] 能说出 checkpoint 粒度与代价的关系
- [ ] 知道批量大小该按什么定
- [ ] 能列出沙箱的五个要素
- [ ] 理解预算闸门为什么要"做之前检查 + 保留现场"

## 16.9 练习

1. 把 `BUDGET_TOKENS` 调到 200，观察在第几批停下、checkpoint 是否正确。
2. 删掉 checkpoint 里几条 `done`，模拟"数据损坏"，看续跑会不会被骗（会重复打分）。
3. 用 `concurrent.futures` 把每批改成并发，处理 `save_ckpt` 的并发写冲突。
