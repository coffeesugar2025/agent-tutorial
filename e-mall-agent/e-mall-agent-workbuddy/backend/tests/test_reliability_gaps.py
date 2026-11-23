"""可靠性与生产化缺口专项测试：限流、熔断、背压、灰度、密钥、保留、告警、环境配置。

全部使用注入的时钟 / 等待函数 / 组件，离线确定性，不依赖真实时间或网络。
"""
from __future__ import annotations

import asyncio

from app.config_profiles import ConfigValidationError, Environment, ProfileConfig
from app.observability.alerting import (
    AlertManager,
    AlertRule,
    HealthProbe,
    SLO,
    resolve_metric,
)
from app.reliability.backpressure import BoundedQueue
from app.reliability.circuitbreaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.reliability.flags import FeatureFlag, FlagRegistry, is_enabled, variant
from app.reliability.ratelimit import TokenBucket
from app.reliability.retention import RetentionManager, RetentionPolicy
from app.reliability.secrets import EnvSecretsProvider, SecretsProvider, SecretRing


# ---------------------------------------------------------------------------
# 一、限流 / 熔断 / 背压
# ---------------------------------------------------------------------------
def test_token_bucket_depletes_and_refills():
    """令牌桶：初始满桶可用，耗尽后补充速率决定恢复量。"""
    now = [0.0]
    bucket = TokenBucket(2, 1, clock=lambda: now[0])
    assert bucket.try_acquire() and bucket.try_acquire()
    assert bucket.try_acquire() is False
    now[0] += 1.0
    assert bucket.available == 1.0
    assert bucket.try_acquire() is True


async def test_token_bucket_async_acquire_with_timeout():
    """异步限流：等待补充后成功；超时则丢弃请求。"""
    now = [0.0]

    async def sleeper(delay: float) -> None:
        now[0] += delay

    bucket = TokenBucket(1, 2, clock=lambda: now[0], sleeper=sleeper)
    assert bucket.try_acquire() is True
    assert await bucket.acquire(timeout=1.0) is True
    assert await bucket.acquire(timeout=0.0) is False


async def test_circuit_breaker_trips_and_recovers():
    """熔断器：连续失败达阈值 -> open -> 冷却后半开 -> 成功恢复 closed。"""
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=0.5, min_calls=3,
                             cooldown_seconds=10, clock=lambda: now[0])

    async def boom() -> None:
        raise ValueError("fail")

    for _ in range(3):
        try:
            await breaker.call(boom)
        except ValueError:
            pass
    assert breaker.state is CircuitState.OPEN
    try:
        await breaker.call(lambda: 1)
    except CircuitOpenError:
        pass
    now[0] += 10.0
    assert breaker.state is CircuitState.HALF_OPEN
    assert await breaker.call(lambda: "ok") == "ok"
    assert breaker.state is CircuitState.CLOSED


async def test_bounded_queue_drops_on_timeout_and_get_timeout():
    """背压：队列满时 put 超时丢弃；队列空时 get 超时返回 None。"""
    now = [0.0]

    async def sleeper(delay: float) -> None:
        now[0] += delay

    queue = BoundedQueue(1, clock=lambda: now[0], sleeper=sleeper)
    assert queue.put_nowait("first") is True
    assert queue.put_nowait("second") is False
    assert await queue.put("second", timeout=0.02) is False
    assert await queue.get() == "first"
    assert await queue.get(timeout=0.01) is None


# ---------------------------------------------------------------------------
# 二、Feature Flag / 灰度 / A-B
# ---------------------------------------------------------------------------
def test_feature_flag_stable_bucket_and_rollout():
    """灰度分桶：同一用户分桶稳定，0%/100% 灰度边界正确。"""
    flag = FeatureFlag("feat", rollout=0.0)
    assert flag.is_enabled("u1") is False
    assert FeatureFlag("feat", rollout=1.0).is_enabled("u1") is True
    assert flag.bucket("u1") == flag.bucket("u1")


def test_feature_flag_whitelist_and_variant():
    """白名单与 A-B：白名单覆盖灰度，变体由同一分桶稳定选择。"""
    flag = FeatureFlag("ab", rollout=0.1, whitelist={"vip"}, variants=["A", "B"])
    assert flag.is_enabled("vip") is True
    assert flag.variant("vip") in {"A", "B"}
    assert flag.variant("vip") == flag.variant("vip")
    assert is_enabled(flag, "vip") is True and variant(flag, "vip") is not None

    registry = FlagRegistry([flag])
    assert registry.is_enabled("ab", "vip") is True
    assert registry.is_enabled("missing", "vip") is False


# ---------------------------------------------------------------------------
# 三、密钥管理与轮换
# ---------------------------------------------------------------------------
def test_secret_ring_sign_verify_and_rotation():
    """密钥环：签名可验签，轮换后旧 token 仍可用，篡改被拒绝。"""
    ring = SecretRing({"k1": "secret-1"}, active_kid="k1")
    old = ring.sign("hello")
    assert ring.verify(old) == "hello"
    new_kid = ring.rotate()
    assert new_kid == ring.active_kid
    assert ring.verify(old) == "hello"
    assert ring.verify(ring.sign("world")) == "world"
    kid, body, signature = old.split(".")
    assert ring.verify(f"{kid}.{body}.{'A' * len(signature)}") is None
    assert ring.verify("k9.body.sig") is None


def test_env_secrets_provider_loads_ring():
    """环境变量加载：ACTIVE_KID 指定当前版本，其余前缀项作为密钥。"""
    env = {"ECOM_SECRET_ACTIVE_KID": "k2", "ECOM_SECRET_K1": "s1",
           "ECOM_SECRET_K2": "s2", "OTHER": "ignored"}
    provider = EnvSecretsProvider(env=env)
    assert isinstance(provider, SecretsProvider)
    ring = SecretRing.from_provider(provider)
    assert ring.kids == ["k1", "k2"] and ring.active_kid == "k2"
    assert ring.verify(ring.sign("payload")) == "payload"


# ---------------------------------------------------------------------------
# 四、数据合规 / 保留策略
# ---------------------------------------------------------------------------
def test_retention_policy_purges_expired_records():
    """保留策略：按数据类型 TTL 清理过期记录并写审计。"""
    audit_calls: list[tuple] = []
    audit = type("Audit", (), {"record": lambda self, *a, **k: audit_calls.append(a)})()
    manager = RetentionManager(
        RetentionPolicy({"cache": 10}), memory=None, audit=audit, clock=lambda: 0.0,
    )
    manager.add("cache", "u1", created_at=0.0)
    manager.add("order", "u2", created_at=0.0)
    assert manager.purge_expired(now=11.0) == 1
    assert len(manager) == 1
    assert audit_calls[0][1] == "purge_expired"


def test_delete_user_data_orchestrates_memory_and_audit():
    """统一删除：清理用户记录、调用 forget_user、写入审计。"""
    calls: list[str] = []

    class Memory:
        def forget_user(self, user_id: str) -> dict[str, int]:
            calls.append(user_id)
            return {"episodes": 2}

    audit_calls: list[tuple] = []
    audit = type("Audit", (), {"record": lambda self, *a, **k: audit_calls.append(a)})()
    manager = RetentionManager(memory=Memory(), audit=audit, clock=lambda: 100.0)
    manager.add("order", "u1")
    manager.add("order", "u2")
    result = manager.delete_user_data("u1")
    assert calls == ["u1"]
    assert result["records"] == 1 and result["memory"] == {"episodes": 2}
    assert audit_calls[0][1] == "delete_user_data"


# ---------------------------------------------------------------------------
# 五、健康检查 / SLO / 告警
# ---------------------------------------------------------------------------
def test_slo_and_alert_rule_on_nested_snapshot():
    """SLO 与告警：嵌套快照中 p99 可被解析，阈值触发方向正确。"""
    snapshot = {"summary": {"success_rate": 0.95,
                            "agent_latency_ms": {"p99": 320},
                            "tool_error_rate": 0.08}}
    assert resolve_metric(snapshot, "p99") == 320.0
    assert SLO("availability", 0.99, "success_rate", ">=").is_met(0.95) is False
    assert SLO("latency", 300, "p99", "<=").is_met(320.0) is False
    assert AlertRule("p99", "p99", 200, ">").evaluate(snapshot) is not None
    assert AlertRule("error", "tool_error_rate", 0.5, ">").evaluate(snapshot) is None


def test_alert_manager_and_health_probe():
    """告警聚合与探活：规则/SLO 汇总产出告警，异常 check 视为不健康。"""
    snapshot = {"p99": 320, "success_rate": 0.9}
    manager = AlertManager(
        [AlertRule("high-p99", "p99", 200, ">")],
        [SLO("availability", 0.99, "success_rate", ">=")],
    )
    alerts = manager.evaluate(snapshot)
    assert {a.severity for a in alerts} == {"warning", "critical"}
    assert all("message" in a.as_dict() for a in alerts)

    probe = HealthProbe()
    probe.register("db", lambda: True)
    probe.register("api", lambda: False)

    async def broken() -> bool:
        raise RuntimeError("down")

    probe.register("broken", broken)
    report = asyncio.run(probe.check_all())
    assert report == {"db": True, "api": False, "broken": False}
    assert asyncio.run(probe.is_healthy()) is False
    assert probe.unregister("broken") is True


# ---------------------------------------------------------------------------
# 六、环境配置隔离
# ---------------------------------------------------------------------------
def test_profile_defaults_and_env_override():
    """环境默认值：dev 开启 debug，staging 关闭；ECOM_* 变量覆盖且做类型转换。"""
    dev = ProfileConfig("dev", env_vars={})
    assert dev.environment is Environment.DEV and dev.get("debug") is True
    staging = ProfileConfig(Environment.STAGING, env_vars={})
    assert staging.get("debug") is False and staging.get("strict_security") is True
    overridden = ProfileConfig("dev", env_vars={"ECOM_DEBUG": "false", "ECOM_RAG_TOP_K": "7"})
    assert overridden.get("debug") is False and overridden.get("rag_top_k") == 7


def test_profile_validation_requires_production_secrets():
    """配置校验：dev 免校验；prod 缺少密钥或使用开发密钥时抛错。"""
    assert ProfileConfig("dev", env_vars={}).validate_or_raise() is True
    try:
        ProfileConfig("prod", env_vars={}).validate_or_raise()
    except ConfigValidationError as exc:
        assert "openai_api_key" in str(exc) and "secret_key" in str(exc)
    else:
        raise AssertionError("prod 缺少密钥时应抛出 ConfigValidationError")
    prod = ProfileConfig("prod", overrides={"secret_key": "real-secret",
                                             "openai_api_key": "sk-real"}, env_vars={})
    assert prod.validate_or_raise() is True
