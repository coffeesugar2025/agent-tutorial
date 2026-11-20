"""第 16 章：长任务 —— 断点续跑、分批、沙箱、预算。

跑法：python ch16_long_task/main.py

一个"跑一晚上"的任务要回答四个问题：
  ① 跑到一半崩了，从哪继续？   → checkpoint 文件 + 幂等键
  ② 一次塞 500 份简历会爆吗？   → 分批 + 批间隔 + 每批上限
  ③ 模型写的代码能直接执行吗？ → 沙箱：白名单、超时、次数、无网络
  ④ 花多少钱？                 → 预算闸门，超了就停并保留现场
"""

import sys, pathlib, json, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from common import ai_text, get_model, practice, section, star, title

WORK = pathlib.Path(__file__).resolve().parent / "_run"
WORK.mkdir(exist_ok=True)
CKPT = WORK / "checkpoint.json"

title("案例 1：断点续跑 —— 崩在 8/12 也能接着跑")

RESUMES = [{"id": f"C100{i}", "years": 2 + i % 5} for i in range(1, 13)]
BATCH = 4


def load_ckpt() -> dict:
    if CKPT.exists():
        return json.loads(CKPT.read_text(encoding="utf-8"))
    return {"done": [], "batch": 0, "spent_tokens": 0}


def save_ckpt(ck: dict) -> None:
    CKPT.write_text(json.dumps(ck, ensure_ascii=False, indent=2), encoding="utf-8")


SCORE_P = ChatPromptTemplate.from_messages([
    ("system", "按年限给候选人打分（0-100）：3 年以上 80+，1-3 年 60-80。只输出数字。"),
    ("human", "{id} 工作年限 {years} 年"),
])
model = get_model([ai_text("82"), ai_text("76"), ai_text("65"), ai_text("88")])
scorer = SCORE_P | model | StrOutputParser()

ck = load_ckpt()
print(f"  上次进度：已完成 {len(ck['done'])} 份，第 {ck['batch']} 批之后中断")

BUDGET_TOKENS = 600          # 预算闸门（教学用小值）
results = []

for bi in range(ck["batch"], (len(RESUMES) + BATCH - 1) // BATCH):
    batch = RESUMES[bi * BATCH:(bi + 1) * BATCH]
    print(f"\n  第 {bi+1} 批（{len(batch)} 份）：")
    for r in batch:
        if r["id"] in ck["done"]:
            print(f"    {r['id']} 已完成，跳过（幂等）")
            continue
        if ck["spent_tokens"] > BUDGET_TOKENS:
            print(f"    ⛔ 预算闸门：已用 {ck['spent_tokens']} tokens > {BUDGET_TOKENS}，停止并保留现场")
            save_ckpt(ck)
            raise SystemExit(0)
        score = scorer.invoke({"id": r["id"], "years": r["years"]})
        ck["spent_tokens"] += 60
        ck["done"].append(r["id"])
        results.append((r["id"], int(score)))
        print(f"    {r['id']} 年限 {r['years']} → {score} 分（累计 {ck['spent_tokens']} tokens）")
        save_ckpt(ck)                       # ★ 每处理一条就落盘，别等整批
    ck["batch"] = bi + 1
    save_ckpt(ck)
    time.sleep(0.2)                          # 批间退避：给下游喘息，也避免触发限流

print(f"\n  完成 {len(ck['done'])} 份，累计 {ck['spent_tokens']} tokens")
print(f"  checkpoint 文件：{CKPT.name}（{CKPT.stat().st_size} bytes）")
star("断点续跑的粒度决定代价：每批落盘 → 崩了最多丢一批；每条落盘 → 最多丢一条")

# ============================================================
# 2) 沙箱
# ============================================================
section("案例 2：模型给的代码不能直接 exec")

ALLOWED = {"print", "len", "sum", "min", "max", "sorted", "range", "abs", "round"}
FORBIDDEN = ("import", "open", "exec", "eval", "__", "subprocess", "os.", "socket")


def sandbox(code: str, max_chars: int = 2000) -> str:
    """★ 教学用的最小沙箱：禁止清单 + 长度上限 + 受限全局变量。

    生产上不要自己写沙箱：用容器/微虚拟机（Docker gVisor、Firecracker、E2B），
    并且无网络、无挂载、CPU/内存/时长都限死。这里的实现只够演示"四道闸"的思路。
    """
    if len(code) > max_chars:
        return "⛔ 代码过长"
    for bad in FORBIDDEN:
        if bad in code:
            return f"⛔ 命中禁止项：{bad}"
    try:
        exec(compile(code, "<sandbox>", "exec"), {"__builtins__": {k: __builtins__[k] if isinstance(__builtins__, dict)
                                                                   else getattr(__builtins__, k) for k in ALLOWED}}, {})
        return "✅ 执行完成（输出见上）"
    except Exception as e:
        return f"⛔ 运行失败：{type(e).__name__}: {e}"


print("  ① 正常计算：", sandbox("print(sum([80, 76, 65, 88]) / 4)"))
print("  ② 读文件：", sandbox("data = open('/etc/passwd').read()"))
print("  ③ 偷环境：", sandbox("import os; print(os.environ)"))
print("  ④ 死循环：", sandbox("while True: pass")[:60] + "…（真沙箱靠超时杀掉，不是靠字符串检查）")
star("字符串黑名单只是第一道闸；真正的隔离靠容器 + 超时 + 无网络。别用黑名单冒充沙箱")

for line in [
    "长任务四件事，缺一件就上不了生产：",
    "① checkpoint（每批/每条落盘）+ 幂等键（重跑不重复写）",
    "② 分批 + 批间隔 + 失败单条重试（不要整批回滚）",
    "③ 沙箱（容器化、无网络、限时限额）",
    "④ 预算闸门（token/时长/金额任一超限就停，并保留现场供人工接手）",
]:
    print(f"    {line}")

practice([
    "把 BUDGET_TOKENS 调到 200，观察它在第几批停下、checkpoint 是否正确",
    "删掉 checkpoint 中间几条 done，模拟'数据损坏'，看续跑逻辑是否会被骗",
    "用 concurrent.futures 把每批改成并发，注意 save_ckpt 的并发写冲突",
])
