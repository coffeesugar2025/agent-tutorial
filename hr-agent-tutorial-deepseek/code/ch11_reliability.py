"""第 11 章：可靠性工程——超时、重试、幂等、熔断与降级（LangChain 版）。

场景：校招季批量给 20 位候选人发面试邀请。邮件服务会超时、会拒收，也可能
「邮件已经发出，但回执没回来」。重试与降级用 LangChain Runnable 的
`with_retry()` / `with_fallbacks()`，熔断、幂等、补偿、对账仍是自定义逻辑。
固定随机种子，离线可复现。
"""
from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.runnables import RunnableLambda

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.data import candidates


class EmailError(Exception):
    """邮件服务错误的基类。"""


class EmailTimeout(EmailError):
    """可重试：超时、连接中断。"""


class EmailRejected(EmailError):
    """不可重试：地址不存在、被网关拒收。"""


class CircuitOpen(EmailError):
    """熔断打开：不再调用下游，直接快速失败。"""


class FlakyEmailService:
    """30% 概率故障的假邮件服务：一半超时（可重试），一半拒收（不可重试）。

    lost_receipt_keys 里的地址会「真的发出去，然后抛出超时」，用来模拟回执丢失。
    """

    def __init__(self, seed: int = 42, fail_rate: float = 0.3):
        self.random = random.Random(seed)
        self.fail_rate = fail_rate
        self.attempts = 0
        self.receipts: dict[str, str] = {}  # 服务端真实发件记录，对账时以它为准
        self.lost_receipt_keys: set[str] = set()
        self.down = False

    def send(self, key: str, to: str) -> str:
        self.attempts += 1
        if self.down:
            raise EmailTimeout("邮件服务不可用（连接被拒绝）")
        if key in self.lost_receipt_keys:
            self.receipts[key] = f"receipt-{key}"  # 邮件确实发出去了
            raise EmailTimeout("回执超时（邮件可能已送达）")
        roll = self.random.random()
        if roll < self.fail_rate / 2:
            raise EmailTimeout("SMTP 超时")
        if roll < self.fail_rate:
            raise EmailRejected("收件人被邮件网关拒收")
        self.receipts[key] = f"receipt-{key}"
        return self.receipts[key]


class CircuitBreaker:
    """三态熔断器：closed 正常放行，open 快速失败，half_open 只放一个探针。"""

    def __init__(self, threshold: int = 4, reset_timeout: float = 0.03):
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.transitions: list[str] = ["closed"]

    def _move(self, state: str) -> None:
        self.state = state
        self.transitions.append(state)

    def before(self) -> None:
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.reset_timeout:
                self._move("half_open")
            else:
                raise CircuitOpen("熔断打开，快速失败")

    def on_success(self) -> None:
        self.failures = 0
        if self.state != "closed":
            self._move("closed")

    def on_failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.threshold:
            self.opened_at = time.monotonic()
            self._move("open")


@dataclass
class IdempotencyStore:
    """幂等键台账：同一个 key 只允许产生一次外部副作用。生产里落 Redis/SQLite 并加 TTL。"""

    records: dict[str, dict] = field(default_factory=dict)

    def get(self, key: str) -> dict | None:
        return self.records.get(key)

    def put(self, key: str, status: str, value: str = "") -> None:
        self.records[key] = {"status": status, "value": value}


def build_invites(count: int = 20, round_offset: int = 0) -> list[dict]:
    people = candidates()
    invites = []
    for index in range(count):
        person = people[index % len(people)]
        round_no = index // len(people) + 1 + round_offset
        invites.append({
            "key": f"interview:{person['id']}:R{round_no}",
            "name": person["name"],
            "email": f"{person['id'].lower()}@example.com",
            "round": round_no,
        })
    return invites


def notify_inapp(store: IdempotencyStore, key: str) -> None:
    store.put(key, "inapp", f"站内信-{key}")


def build_chain(service: FlakyEmailService, store: IdempotencyStore, breaker: CircuitBreaker):
    """发信 Runnable：with_retry 负责退避重试，with_fallbacks 负责降级到站内信。"""
    send = RunnableLambda(lambda payload: service.send(payload["key"], payload["email"])).with_retry(
        retry_if_exception_type=(EmailTimeout,),  # 拒收重试没用，不纳入
        stop_after_attempt=2,
        wait_exponential_jitter=True,
        exponential_jitter_params={"initial": 0.01, "max": 0.05},
    )

    def guarded(payload: dict) -> str:
        breaker.before()  # 熔断打开时直接抛 CircuitOpen，交给 fallbacks
        try:
            receipt = send.invoke(payload)
        except EmailTimeout:
            breaker.on_failure()
            raise
        breaker.on_success()
        return receipt

    guarded_runnable = RunnableLambda(guarded)

    def fallback(payload: dict) -> str:
        notify_inapp(store, payload["key"])
        return "inapp"

    chain = guarded_runnable.with_fallbacks(
        [RunnableLambda(fallback)],
        exceptions_to_handle=(EmailTimeout, EmailRejected, CircuitOpen),
    )
    return chain, guarded_runnable


def send_invite(chain, store: IdempotencyStore, invite: dict) -> str:
    """返回 success / duplicate / failed。已成功的 key 永不重发。"""
    record = store.get(invite["key"])
    if record and record["status"] == "sent":
        return "duplicate"
    outcome = chain.invoke({"key": invite["key"], "email": invite["email"]})
    if outcome == "inapp":
        return "failed"
    store.put(invite["key"], "sent", outcome)
    return "success"


def run_batch(invites: list[dict], chain, store: IdempotencyStore) -> dict:
    stats = {"success": 0, "duplicate": 0, "failed": 0, "failed_keys": []}
    for invite in invites:
        outcome = send_invite(chain, store, invite)
        stats[outcome] += 1
        if outcome == "failed":
            stats["failed_keys"].append(invite["key"])
    return stats


def main() -> None:
    def section(title: str) -> None:
        print(f"\n=== {title} ===")

    invites = build_invites(20)
    service = FlakyEmailService(seed=42)
    service.lost_receipt_keys = {"interview:C003:R1"}  # 指定一封用于“回执丢失”对账
    store, breaker = IdempotencyStore(), CircuitBreaker(threshold=4, reset_timeout=0.03)
    chain, guarded = build_chain(service, store, breaker)
    section("1. 批量发送 20 封面试邀请（失败率 30%，with_retry 最多 2 次尝试）")
    stats = run_batch(invites, chain, store)
    print(f"成功 {stats['success']}，重复 {stats['duplicate']}，失败 {stats['failed']}，"
          f"SMTP 调用 {service.attempts} 次")
    section("2. 对账：发送成功但回执丢失的，不能当失败重发")
    lost = [key for key in stats["failed_keys"] if key in service.receipts]
    for key in lost:
        store.put(key, "sent", service.receipts[key])
    remaining = [key for key in stats["failed_keys"] if key not in service.receipts]
    print(f"回执丢失但实际已发送：{len(lost)} 条 -> {lost}")
    print(f"确认失败、已降级站内信：{len(remaining)} 条 -> {remaining}")
    section("3. 幂等：重发已经成功的 5 封，不应产生新的 SMTP 调用")
    sent = [invite for invite in invites if (store.get(invite["key"]) or {}).get("status") == "sent"][:5]
    before = service.attempts
    outcomes = [send_invite(chain, store, invite) for invite in sent]
    after_dup = service.attempts
    print(f"重发 {len(sent)} 条：重复 {outcomes.count('duplicate')}，新增 SMTP 调用 "
          f"{after_dup - before} 次")
    section("4. 熔断：邮件服务整体不可用，4 次失败后快速失败并降级")
    service.down = True
    down_invites = build_invites(6, round_offset=3)
    down_stats = run_batch(down_invites, chain, store)
    print(f"6 条请求：成功 {down_stats['success']}，失败 {down_stats['failed']}；"
          f"熔断状态 {breaker.state}，迁移路径 {' -> '.join(breaker.transitions)}")
    print(f"降级站内信：{len(down_stats['failed_keys'])} 条")
    section("5. 冷却后再试一次：half_open 探针失败，重新打开")
    time.sleep(0.06)
    try:
        guarded.invoke({"key": "probe:1", "email": "probe@example.com"})
    except (EmailTimeout, CircuitOpen) as exc:
        print(f"探针结果：{type(exc).__name__}: {exc}；状态 {breaker.state}")
    print("状态迁移：" + " -> ".join(breaker.transitions))
    counts = {"sent": 0, "inapp": 0, "failed": 0}
    for record in store.records.values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(f"\n台账统计：{counts}")
    assert stats["success"] + stats["failed"] == 20 and len(lost) >= 1, "20 封邀请都要有结果，且要演示回执丢失"
    assert outcomes.count("duplicate") == 5 and after_dup == before, "重复请求不应重发"
    assert breaker.state == "open" and "half_open" in breaker.transitions, "三态都要走到"
    assert len(down_stats["failed_keys"]) == 6, "服务不可用时全部降级而不是静默丢失"
    print("\n断言通过：with_retry、with_fallbacks、幂等、对账、熔断与降级都按预期工作。")


if __name__ == "__main__":    main()
