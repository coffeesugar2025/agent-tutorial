---
title: "14 | Sandbox、Code Mode 与长任务恢复"
slug: "sandbox-longtask"
order: 14
part: "生产级可靠性"
minutes: 70
difficulty: "高阶"
prerequisites: ["13"]
summary: "用 AST 白名单与子进程隔离模型代码，并用 checkpoint 让长任务断点续跑。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`@tool`、`create_agent`、沙箱执行。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch14_sandbox.py`。


## 0. 本章你会得到什么

学完这章，你应该能：

1. 说清为什么不能对模型生成的代码直接 `eval`，以及“黑名单”为什么靠不住。
2. 用 AST（Abstract Syntax Tree，抽象语法树）白名单实现一个只做四则、比较和聚合的 `safe_eval`。
3. 用 `sys.executable` + `subprocess.run(timeout=...)` 在独立进程里跑不可信代码，超时直接杀掉。
4. 用 checkpoint 让 50 份简历的解析任务在第 23 份崩溃后继续跑，并保证结果不重复。
5. 理解 Code Mode：让模型写一小段聚合代码，而不是逐条调用工具 50 次。

这章的关键词是**边界**：模型可以写代码，但代码在哪儿跑、能碰什么、跑多久、崩了怎么办，必须由你决定。

## 1. 场景

10 月 8 日，周一。HRBP 赵敏接过一个“两天内做完”的任务：把 1000 份校招简历打上技能标签，统计每个技能出现多少次，供业务部门确定面试优先级。

她算了一笔账：一份简历调一次模型打标签，1000 次调用；按每次 1.2 秒、2000 token 估算，光模型调用就要 20 分钟、200 万 token，而且中间只要网络抖一下，就得从头再来。

更聪明的做法是：给模型看 3 份样例和字段结构，让它写一段 Python，一次性跑完 1000 份。为了让示例能在几秒内跑完，本章的代码用 8 位种子候选人的数据扩充出 50 份简历，流程和 1000 份完全一样。模型很快返回：

```python
import json
rows = json.load(open("resumes.json"))
result = {}
for row in rows:
    for skill in row["skills"]:
        result[skill] = result.get(skill, 0) + 1
print(json.dumps(result))
```

问题来了：这段代码要在**你的服务器**上跑。它今天只是读 `resumes.json`，明天可能是：

- `os.remove("C:/...")` 删文件；
- 读环境变量里的 `HR_LLM_API_KEY`；
- `while True: pass` 死循环，把 CPU 占满；
- 访问内网数据库。

模型不是攻击者，但它会犯错，也会被提示注入利用。**把“模型生成的代码”当成“陌生同事发来的附件”**，是最基本的心态。

## 2. 概念

### 2.1 三层边界：语法、进程、资源

一个能用的沙箱不是单一技术，而是三层叠加：

```text
┌──────────────── 宿主进程（有密钥、有数据库连接）─────────────────┐
│  模型 → 代码文本 → AST 白名单 ──拒绝──> 记录原因，不执行          │
│                              │ 放行                              │
│                     ┌────────v─────────┐                         │
│                     │ 子进程（无密钥）  │  timeout=0.4s           │
│                     │ 只读临时目录      │  超时 kill              │
│                     └────────┬─────────┘                         │
│                              │ stdout(JSON)                     │
│                     ┌────────v─────────┐                         │
│                     │ 结果校验后入库    │                         │
│                     └──────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
```

- **语法层**：只放行你认识的节点，其余一律拒绝。它便宜、快，能挡住 90% 的误用。
- **进程层**：真正执行时，放到独立子进程，环境变量清理、工作目录隔离、stdin 关闭。
- **资源层**：超时、内存、CPU、文件系统、网络。本章只做超时，生产要补齐其余。

三层缺一不可：只有 AST 会被“语法合法但语义危险”的代码绕过；只有子进程则每次都要付启动成本，而且错误代码会浪费资源。

### 2.2 为什么黑名单靠不住

很多人第一反应是“禁止 `import`、禁止 `open`、禁止 `__`”。黑名单的问题是：你永远不知道下一个绕过方式。

```python
().__class__.__bases__[0].__subclasses__()
```

这行没有 `import`、没有 `open`，但它能拿到 Python 里的几乎任意类。类似技巧还有 `getattr`、`eval`、`exec`、`compile`、`globals`、`__builtins__`。你封一个，攻击者换一个。

白名单反过来：**只列允许的，没列的一律拒绝。** 本章的 `safe_eval` 只认识：

| 类别 | 允许 | 拒绝示例 |
| --- | --- | --- |
| 常量 | 数字、字符串、布尔、`None` | 自定义对象 |
| 四则 | `+ - * /` | `**`、`//`、`%` |
| 比较 | `== != < <= > >=` | `in`、`is` |
| 容器 | 列表、元组字面量 | 字典、集合、推导式 |
| 调用 | `sum/len/min/max` | 其余任何函数 |
| 其他 | 一元正负号 | 属性、下标、lambda、循环、条件表达式 |

注意 `**` 也被拒绝：`2 ** 999999999` 会让进程卡死。白名单不只是“安全”，也是“防资源耗尽”。

### 2.3 `run_in_subprocess`：超时是硬约束

`safe_eval` 只适合“表达式级”的计算，比如算个薪资差额、判断阈值。真正跑批处理代码，必须用子进程：

```text
父进程：写临时脚本 → subprocess.run([python, script], timeout=0.4)
                         │
                         ├─ 正常结束 → 读 stdout / returncode
                         └─ 超时 → TimeoutExpired → 子进程被 kill
```

`subprocess.run(timeout=...)` 在超时时会杀掉子进程并抛 `TimeoutExpired`。这比自己写 `Popen + poll` 简单，也足够应付“死循环”这种最常见的事故。

但超时不是万能的：

- 子进程可能先 `fork` 出孙进程，杀父进程不等于杀孙进程；生产上要用进程组/Job Object。
- 超时只限制“时间”，不限制内存；一个 `[0] * 10**9` 能瞬间吃光内存。
- 子进程仍然继承环境变量；要显式传一个干净的环境。

本章的示例把 `cwd` 设成临时目录、死循环示例超时 0.4 秒，已经能挡住“死循环”和“乱写文件”两类最常见问题。

### 2.4 checkpoint：至少一次，而不是恰好一次

长任务崩溃后，最自然的想法是“从上次成功的地方继续”。但“上次成功”到底以什么为准？

本章的 `LongTask` 每处理 10 份，就把 `next_index` 和已完成结果写进 JSON。第 23 份崩溃时：

```text
R001 ... R010  [checkpoint: 10]
R011 ... R020  [checkpoint: 20]
R021 R022      （已处理，但还没到 10 的倍数，未写盘）
R023           ✗ 进程被杀
                    ↓ resume
R021 R022      （重做一次）
R023 ... R050  [checkpoint: 30, 40, 50]
```

关键认知：**checkpoint 是“至少一次”（at-least-once），不是“恰好一次”（exactly-once）。** 崩溃前已处理但未落盘的两条，恢复后会被重做。这没关系，只要写入是按 `id` 覆盖的（幂等），最终结果就不会重复。

反过来，如果你的“处理”有外部副作用（发邮件、扣款、调用第三方），重做就会重复发邮件。这时要么把副作用也做成幂等（带幂等键），要么把“写结果”和“记 checkpoint”放进同一个事务。

### 2.5 Code Mode：让模型写代码，而不是一步步调工具

传统工具调用是“模型 → 工具 → 结果 → 模型 → 工具……”。50 份简历就要 50 轮，每轮都把上下文重新发一遍，又慢又贵。

Code Mode 换了个思路：模型只写一段代码，代码在沙箱里一次性处理全部数据，只把最终结果返回。

| 维度 | 逐步工具调用 | Code Mode |
| --- | --- | --- |
| 模型调用次数 | 每份一次，50 次 | 1 次生成代码 |
| 模型看到的上下文 | 50 份简历全文 | 字段结构 + 3 份样例 |
| 延迟 | 50 次往返 | 1 次生成 + 1 次本地执行 |
| 风险 | 单次调用失败可重试 | 代码不可信，必须沙箱 |
| 适合 | 需要逐条判断、解释 | 聚合、过滤、批量转换 |

Code Mode 的前提是：**你有一个能安全执行代码的沙箱，以及一个稳定的数据接口。** 否则就是把“模型幻觉”升级成“模型写的程序在生产库上跑”。

### 2.6 LLM 在 Code Mode 里的位置

模型只做一件事：把“我要统计技能分布”翻译成代码。它不执行代码，也看不到全量数据（只看到 schema 和样例）。执行、校验、限流、超时，全部由宿主负责。

这和上一章的合规判定是同一条原则：**让模型做它擅长的（生成、总结、解释），让确定性代码做它必须保证的（权限、校验、执行、审计）。**

### 2.7 Harness：把模型、工具、沙箱、评测装进一个执行框架

Sandbox 只是 Harness 的一个部件。Harness（执行框架/运行时）负责一次 Agent 运行的全部环境：

```text
Harness
├─ Loop / 终止条件 / 重试
├─ Context / 工具注册 / 权限
├─ Sandbox（本章）
├─ HITL 审批 / 中断恢复
├─ State / checkpoint（本章）
└─ Trace / 指标 / 评测（第 15 章）
```

同一个模型放进不同的 Harness，可靠性差别可能比换模型还大：有没有步数上限、工具结果会不会被截断、崩溃能不能恢复、敏感操作有没有审批、失败能不能复盘。选型时先看这些，再看模型榜单。

> 📌 **考点**：面试官问“你们用的什么 Agent 框架”，不要只报名字。说清它提供了哪些 Harness 能力（状态、沙箱、审批、Trace），以及你自己补了哪些。更多生态对比见 `docs/appendix/ecosystem.md`。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


完整代码在 `code/ch14_sandbox.py`，从仓库根目录运行：

```powershell
python code/ch14_sandbox.py
```

第一段是 AST 白名单的核心。它递归检查每个节点，遇到不认识的就抛 `UnsafeCode`：

```python
def _check(node):
    if isinstance(node, ast.Expression):
        _check(node.body)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool, type(None))):
            raise UnsafeCode("不允许的常量类型")
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, BIN_OPS):
            raise UnsafeCode("只允许 + - * / 四则运算")
        _check(node.left)
        _check(node.right)
    elif isinstance(node, ast.Compare):
        if not all(isinstance(op, CMP_OPS) for op in node.ops):
            raise UnsafeCode("只允许 == != < <= > >=")
        _check(node.left)
        for comparator in node.comparators:
            _check(comparator)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            raise UnsafeCode("只允许调用 sum/len/min/max")
        for argument in node.args:
            _check(argument)
    else:
        raise UnsafeCode(f"禁止的语法：{type(node).__name__}")
```

第二段是 `safe_eval`。它先解析、再检查、最后才 `eval`，且全局变量里只有四个函数：

```python
SAFE_GLOBALS = {"__builtins__": {}, "sum": sum, "len": len, "min": min, "max": max}

def safe_eval(expression):
    tree = ast.parse(expression, mode="eval")
    _check(tree)
    return eval(compile(tree, "<safe_eval>", "eval"), SAFE_GLOBALS, {})
```

第三段是子进程隔离。注意超时用 `0.4` 秒，只够跑完一个小脚本；死循环会被 `TimeoutExpired` 杀掉：

```python
def run_in_subprocess(code, timeout=0.4):
    with tempfile.TemporaryDirectory(prefix="ch14_sub_") as tmp:
        script = Path(tmp) / "job.py"
        script.write_text(code, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "", "timed_out": True}
        return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "timed_out": False}
```

第四段是长任务。`next_index` 指向下一份要处理的数据，`results` 以简历 id 为键：

```python
def run(self, fail_at=None):
    self._load()
    for index in range(self.next_index, len(self.items)):
        if fail_at is not None and index == fail_at:
            raise SimulatedCrash(f"进程在第 {index + 1} 份简历前被杀死")
        item = self.items[index]
        self.results[item["id"]] = self._process(item)
        self.work_log.append(item["id"])
        self.next_index = index + 1
        if self.next_index % self.batch_size == 0:
            self._save()
    self._save()
```

运行后，你会看到：

- `safe_eval` 正确算出 `1333.33`、`8`、`12`、`True`；
- 8 个攻击样例全部被拒绝，理由分别是“只允许调用 sum/len/min/max”“禁止 Subscript”“禁止 ListComp”“只允许四则”等；
- 正常子进程输出 `42`，死循环在 `0.4` 秒后 `timed_out=True`；
- 长任务崩溃时内存 22 条、磁盘 checkpoint 20 条；恢复后从 `R021` 开始，处理 30 条，最终 50 条无重复；
- Code Mode 的恶意代码因 `Import` 被拒；正常聚合得到 `Python 19、Go 7、MySQL 7、微服务 7、Vue3 7`，与长任务统计完全一致。

## 4. 逐行拆解

### 4.1 为什么先 `compile` 再 `eval`

`eval` 接受字符串、代码对象或 AST。本章先 `ast.parse`，再 `compile(tree, ...)`，最后 `eval`。这样做的好处是：**检查和执行用的是同一棵树**，不会出现“检查的是 A、执行的是 B”的窗口。

如果你直接 `eval(expression)`，Python 内部还会再解析一次；虽然结果通常一样，但白名单的意义就在于“我检查过的东西，就是我要跑的东西”。编译后的代码对象不可变，更让人放心。

### 4.2 `__builtins__: {}` 不是可选项

Python 的 `eval` 默认会注入完整的 builtins：`open`、`__import__`、`eval`、`exec`、`getattr`……即使白名单漏了某个节点，只要 builtins 被清空，攻击面也会小很多。

本章还只注入了四个函数：

```python
SAFE_GLOBALS = {"__builtins__": {}, "sum": sum, "len": len, "min": min, "max": max}
```

这样 `sum([1,2,3])` 能跑，`open("x")` 会 `NameError`。注意：这不是“安全保证”，只是一个纵深防御层；真正的保证来自 AST 白名单。

### 4.3 子进程超时为什么要 0.4 秒

超时太短，正常脚本会被误杀；太长，死循环会拖慢整个测试。本章的脚本只做 `print(6*7)`，Python 启动 + 执行通常 0.1 秒以内，0.4 秒足够；而死循环会在 0.4 秒时被杀，整个脚本仍然很快。

真实系统里，超时要按任务类型配置：单条表达式 100ms，单份简历解析 2s，整批聚合 30s。不要用一个全局值，也不要让用户能随意改大。

### 4.4 为什么 checkpoint 存 `next_index` 而不是“已处理 id 列表”

存 id 列表也能恢复，但会随着数据量增长而膨胀；存 `next_index` 是 O(1)，而且天然对应“顺序处理”。

代价是：**要求数据顺序稳定**。如果两次运行之间简历列表被重新排序、插入、删除，`next_index` 就会错位。生产上要满足以下之一：

- 输入是不可变快照（带 `snapshot_id`）；
- 按稳定主键排序后再处理；
- checkpoint 同时存“最后处理的 id”和“快照版本”，恢复时校验。

本章为了简单，直接用固定列表，所以 `next_index` 足够。

### 4.5 Code Mode 的校验为什么允许循环和下标

`safe_eval` 拒绝下标和循环，因为它是“表达式求值器”；Code Mode 的聚合代码必须遍历列表、访问 `resume["skills"]`，所以需要另一套白名单。

`validate_aggregate` 允许 `Assign/For/If/Subscript`，但禁止 `Import/Attribute/Call`。这意味着：

- 代码可以读 `data`、写 `result`、遍历、比较；
- 代码不能调用任何函数（连 `len` 都不行），不能访问属性，不能导入模块。

这是一个“够用就好”的窄接口：聚合任务不需要函数调用，就不给。接口越窄，审计越容易。

## 5. 实验

**实验一：把 `**` 加进 `BIN_OPS`。** 运行 `safe_eval("2 ** 10")`，预期得到 `1024`；再运行 `safe_eval("2 ** 999999999")`，观察进程会卡多久。这个实验说明：白名单的“功能”和“资源风险”是两件事，加功能前先想清楚代价。

**实验二：把 `sum` 从 `ALLOWED_CALLS` 里去掉。** 预期：`safe_eval("sum([1,2,3])")` 被拒绝，但 `safe_eval("1+2")` 仍正常。想一想：如果业务只需要四则，为什么还要保留 `sum/len/min/max`？

**实验三：把 checkpoint 的 `batch_size` 从 10 改成 5。** 预期：崩溃时磁盘上保存的条数从 20 变成 20（第 23 份崩溃时，5 的倍数是 20），但恢复时重做的条数从 2 变成 2；如果改成 20，磁盘只保存 20，重做 2 条；如果改成 1，每份都存，重做 0 条但 I/O 变多。记录“重做条数 / 写盘次数”的权衡。

**实验四：给子进程加内存限制。** 在 Linux 上可用 `resource.setrlimit`；Windows 上可用 Job Object。先不做，只讨论：为什么“超时”挡不住 `[0] * 10**9`？

## 6. 工程化视角

**第一，沙箱不是 `eval` 加个 if。** 生产上至少要有：独立容器/微虚拟机（gVisor、Firecracker）、只读根文件系统、无网络、内存/CPU 配额、进程数限制、临时目录隔离、环境变量白名单。本章的 AST + 子进程只是最小演示。

**第二，密钥不能进沙箱。** 子进程继承父进程的环境变量，这是最常见的泄漏路径。执行前要构造一个干净的环境：只保留 `PATH`、`LANG` 等必要变量，把 `HR_LLM_API_KEY`、数据库密码全部剔除。更好的做法是让沙箱跑在一个根本没有这些密钥的容器里。

**第三，Code Mode 要定义“工具 API”，而不是“任意 Python”。** 本章让代码直接遍历 `data`，是因为数据已经序列化进脚本。生产上更稳的做法是提供一组受控函数（`read_rows`、`write_result`），代码只能调用这些函数；网络、文件、数据库都由宿主代理。

**第四，长任务要有心跳和超时。** 除了 checkpoint，还要记录“最后一次心跳时间”。如果一个任务 10 分钟没有心跳，就判定 Worker 失联，交给另一个 Worker 接管；接管前要先确认原 Worker 真的停了，避免两个 Worker 同时写。

**第五，结果要可校验。** Code Mode 的输出不能直接入库。至少要校验：字段齐全、类型正确、总数与输入一致、抽样人工核对。聚合结果和逐条统计对不上，就是一个明确的失败信号。

**第六，checkpoint 要和业务事务对齐。** 如果“处理一份简历”包含“写数据库 + 发消息”，那么 checkpoint 必须在这两件事都成功之后写；否则恢复后可能重复发消息。更稳的是把“处理结果”和“checkpoint”放在同一个数据库事务里。

> ⚠️ **生产提醒**：不要用 `subprocess.run(..., shell=True)` 执行模型生成的代码。`shell=True` 会把代码交给 shell 解析，模型只要写一个 `;` 或 `&&` 就能执行任意命令；本章始终用列表参数 + `sys.executable`。

> ⚠️ **生产提醒**：checkpoint 文件不要放在临时目录里指望“自动清理”。生产上要放在持久化存储（对象存储/数据库），并设置保留策略；临时目录只适合演示。

## 7. 常见坑

**坑一：直接用 `eval` 跑模型代码。** 现象：本地测试没问题，线上被人读走环境变量。原因：`eval` 拥有进程的全部权限。解法：AST 白名单 + 清空 builtins + 子进程隔离。

**坑二：用黑名单“禁止 import”。** 现象：换个 `__subclasses__` 就绕过了。原因：黑名单永远列不全。解法：白名单，只放行需要的节点。

**坑三：子进程没有超时。** 现象：一个 `while True` 把 CPU 跑满，任务队列堵死。原因：`subprocess.run` 没传 `timeout`。解法：强制超时 + 进程组清理 + 监控。

**坑四：checkpoint 写在副作用之后。** 现象：恢复后重复发面试邮件。原因：先发邮件、后写 checkpoint，中间崩溃。解法：幂等键 + 事务性 outbox，或者把副作用也纳入 checkpoint。

**坑五：以为 `next_index` 永远可靠。** 现象：两次运行之间数据被重新排序，漏处理或重复处理。原因：输入不是稳定快照。解法：快照 id + 稳定排序 + 版本校验。

**坑六：临时文件不清理。** 现象：跑一个月后磁盘满了。原因：`NamedTemporaryFile` 用完没删。解法：`TemporaryDirectory` 上下文管理器，异常也能清理；生产上再加定期清扫。

## 8. 练习

**练习一（基础）**：给 `safe_eval` 增加 `//`（整除）支持，并补一个测试 `safe_eval("7 // 2") == 3`。再想一想：`//` 和 `/` 相比，有没有额外的资源风险？

**练习二（进阶）**：把 `LongTask` 的 checkpoint 从 JSON 换成 SQLite，表结构包含 `resume_id/level/skills/processed_at`，并保留 `next_index`。要求：恢复后结果不重复，且能按 `level` 统计。

**练习三（进阶）**：给 `run_in_subprocess` 增加“内存超限”检测（提示：Windows 可用 Job Object，Linux 可用 `resource.setrlimit`；只要求写思路和关键代码，不要求跨平台跑通）。

**练习四（挑战）**：设计一个 Code Mode 的受控 API：模型生成的代码只能调用 `read_resumes()`、`count_skill(skill)`、`emit(result)`，不能直接访问文件。写出 AST 校验规则，并说明它比“允许任意 Python”多防住了什么。

<details>
<summary>参考答案</summary>

**练习一**：把 `ast.FloorDiv` 加进 `BIN_OPS`，测试 `safe_eval("7 // 2") == 3`。风险：`//` 本身不会像 `**` 那样爆炸，但除以 0 会抛 `ZeroDivisionError`，要捕获并转成业务错误。真正要小心的是“大整数除法”，Python 的大整数运算仍然可能消耗 CPU，所以输入长度也要限制。

**练习二**：建表：

```sql
CREATE TABLE result (
  resume_id TEXT PRIMARY KEY,
  level TEXT NOT NULL,
  skills TEXT NOT NULL,
  processed_at TEXT NOT NULL
);
CREATE TABLE progress (id INTEGER PRIMARY KEY CHECK (id = 1), next_index INTEGER NOT NULL);
```

每处理一份，`INSERT OR REPLACE INTO result`，每 10 份更新 `progress`。恢复时读 `progress.next_index`，结果表天然按主键去重。按 `level` 统计用 `GROUP BY level`。注意：结果写入和进度更新要放在同一个事务里。

**练习三**：Windows 上用 Job Object：创建 Job，设置 `JOB_OBJECT_LIMIT_PROCESS_MEMORY`，把子进程加入 Job，超限时子进程被杀。Linux 上用 `resource.setrlimit(RLIMIT_AS, (limit, limit))`，在 `preexec_fn` 里设置。思路：内存限制必须作用在子进程上，不能只在父进程检查；同时要处理“子进程被 kill 后返回码非 0”的情况。

**练习四**：AST 规则：只允许 `Assign`（目标为 `result`）、`Expr`（调用受控函数）、`For`（遍历 `read_resumes()` 的返回值）；`Call` 的函数名必须在 `{"read_resumes", "count_skill", "emit"}` 里；禁止 `Import/Attribute/Subscript`（数据通过 API 返回，不需要下标）。它比“任意 Python”多防住了：直接读文件、访问环境变量、绕过计数逻辑、把结果写到别处。受控 API 还能统一做权限和审计。

</details>

## 9. 小结与下一章

三句话记住这章：

1. **沙箱是三层：语法白名单、进程隔离、资源限制。** 只做一层，等于没做。
2. **checkpoint 是“至少一次”。** 恢复后允许重做，但写入必须按 id 幂等，副作用必须有幂等键。
3. **Code Mode 让模型写代码，不让他跑代码。** 校验、执行、超时、审计，全部由宿主负责。

到这儿，系统能跑、能恢复、能隔离了。但你怎么证明它“变好了”？下一章我们讲可观测性与评测：Trace、指标、Golden Case、回归门禁，以及怎么用数据而不是感觉，判断一次改动到底值不值。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **@tool 沙箱 + create_agent Code Mode**，完整代码见 `code/ch14_sandbox.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain.agents import create_agent
from langchain_core.tools import tool

@tool
def run_aggregate_code(code: str) -> str:
    """在 AST 白名单 + 子进程超时的沙箱里执行模型生成的聚合代码。"""
    validate_aggregate(code)
    return run_in_subprocess(code, timeout=0.4)

agent = create_agent(model=MockChatModel(script=[...]), tools=[run_aggregate_code])
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 沙箱工具 | `@tool` |
| Code Mode | `create_agent` |
| 长任务 | JSON checkpoint / saver |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch14_sandbox.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
