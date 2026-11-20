"""第 15 章：可靠性 —— 重试、超时、降级、幂等、熔断。

跑法：python ch15_reliability/main.py

LangChain 自带的三个原语：
  · runnable.with_retry(...)      —— 只对**可重试的错误**重试，指数退避
  · runnable.with_fallbacks([...]) —— 主模型挂了走备模型，再挂走规则兜底
  · RunnableLambda + asyncio.wait_for —— 超时（LCEL 本身不带 timeout，要自己包一层）

自己必须写的两件：
  · 幂等键（同一个请求重发 3 次，只应产生 1 条记录）
  · 熔断（连续失败到阈值，直接短路，别再打下游）
"""

import sys, pathlib, time, asyncio

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.runnables import RunnableLambda

from common import ai_text, get_model, practice, section, star, title

title("案例 1：重试 —— 不是所有错误都值得重试")

calls = {"n": 0}


def flaky(x):
    """前两次必失败，第三次成功：模拟下游 502 / 限流。"""
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError(f"第 {calls['n']} 次调用：上游 502")
    return f"成功（第 {calls['n']} 次尝试）"


chain = RunnableLambda(flaky).with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
print(f"  结果：{chain.invoke({'q': 'x'})}")

# 不可重试的错误：重试只会放大成本
perm = RunnableLambda(lambda x: (_ for _ in ()).throw(PermissionError("参数非法：emp_id 格式不对")))
try:
    perm.with_retry(stop_after_attempt=3).invoke({})
except PermissionError as e:
    print(f"  不可重试错误：{e}（这类错误重试 3 次只是浪费钱）")

star("重试只对'瞬时故障'（超时、502、限流）；参数错误、权限错误、业务校验失败 —— 一律不重试")

# ============================================================
# 2) 超时：LCEL 不带，要自己包
# ============================================================
section("案例 2：超时 —— 没有超时的调用等于没有上限的成本")


async def slow(x):
    await asyncio.sleep(3)
    return "迟到的答案"


async def with_timeout(x, seconds: float):
    try:
        return await asyncio.wait_for(slow(x), timeout=seconds)
    except asyncio.TimeoutError:
        return f"⛔ 超时 {seconds}s，已放弃并转兜底"


print(f"  1.0s 上限：{asyncio.run(with_timeout({}, 1.0))}")
print(f"  5.0s 上限：{asyncio.run(with_timeout({}, 5.0))}")

# ============================================================
# 3) 降级链：真模型 → 备模型 → 规则兜底
# ============================================================
section("案例 3：with_fallbacks —— 三级降级")

primary = get_model([ai_text("主模型答案")])
backup = get_model([ai_text("备模型答案")])
rule = RunnableLambda(lambda x: "规则兜底：请在 OA 里查看最新余额")

# 让主模型直接抛错，看降级是否生效
broken = RunnableLambda(lambda x: (_ for _ in ()).throw(RuntimeError("主模型 500")))
hi = get_model([ai_text("备模型接住了")])
chain_fb = broken.with_fallbacks([hi, rule])
print(f"  主模型报错时：{chain_fb.invoke('查年假').content}")

for line in [
    "降级的三个层次（越靠下越便宜、越稳、越难看）：",
    "① 换模型（同厂商另一个区域/另一个版本）",
    "② 换小模型（复杂推理 → 简单抽取，质量降一档）",
    "③ 退化为规则/固定话术（'请到 OA 自助查询'）—— 必须有这一层",
]:
    print(f"    {line}")

# ============================================================
# 4) 幂等
# ============================================================
section("案例 4：幂等 —— 重发三次只能有一条记录")

class IdempotentWriter:
    def __init__(self):
        self.records: dict[str, dict] = {}
        self.attempts = 0

    def submit(self, idem_key: str, payload: dict) -> str:
        self.attempts += 1
        if idem_key in self.records:
            return f"命中幂等键，返回已有记录 {self.records[idem_key]['id']}"
        rid = f"R{len(self.records) + 1}"
        self.records[idem_key] = {"id": rid, **payload}
        return f"新建记录 {rid}"


w = IdempotentWriter()
key = "leave:E1001:2026-12-01:年假"
for i in range(3):
    print(f"  第 {i+1} 次提交 → {w.submit(key, {'emp_id': 'E1001', 'days': 2})}")
print(f"  尝试 {w.attempts} 次，实际记录 {len(w.records)} 条")
star("幂等键要由业务语义拼：谁 + 什么事 + 哪个时间点。用随机 UUID 做键，等于没有幂等")

# ============================================================
# 5) 熔断
# ============================================================
section("案例 5：熔断 —— 下游已经挂了，别再送人头")

class Breaker:
    def __init__(self, threshold: int = 3, cooldown: float = 10):
        self.threshold, self.cooldown = threshold, cooldown
        self.fails, self.open_at = 0, 0.0

    def call(self, fn):
        if time.time() < self.open_at:
            return "⛔ 熔断中，直接返回兜底（不再调用下游）"
        try:
            r = fn()
            self.fails = 0
            return r
        except Exception as e:
            self.fails += 1
            if self.fails >= self.threshold:
                self.open_at = time.time() + self.cooldown
            return f"失败（累计 {self.fails}）：{e}"


cb = Breaker()
for i in range(5):
    print(f"    第 {i+1} 次：{cb.call(lambda: (_ for _ in ()).throw(TimeoutError('下游超时')))}")

print("\n  四件套的分工（别混）：")
for line in [
    "重试：这次失败可不可以再试一次？（瞬时故障）",
    "超时：等多久就该放弃？（成本上限）",
    "降级：放弃之后用什么代替？（用户体验下限）",
    "熔断：连续失败到多少就别再试？（保护下游与预算）",
]:
    print(f"    {line}")

practice([
    "把 with_retry 换成 stop_after_attempt=1，看 flaky 的表现（应该直接失败）",
    "给 Breaker 加 half-open 状态：冷却后放一个请求试探",
    "把幂等键存到 sqlite，进程重启后验证仍然去重",
])
