"""Reliability 能力专项测试：重试、超时、降级、幂等、终止条件与一站式装配。

每个用例都用中文 docstring 说明「知识点 -> 验证点」。
"""
from __future__ import annotations

import asyncio

import pytest

from app.reliability import (
    AgentTimeoutError,
    FallbackChain,
    FallbackExhausted,
    IdempotencyGuard,
    ResilienceConfig,
    RetryPolicy,
    StopConditions,
    StopRequestedError,
    StopState,
    TimeoutPolicy,
)


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self):
        """重试：前两次失败后第三次成功，重试回调被触发两次。"""
        attempts = 0
        events: list[tuple[int, float]] = []

        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("临时失败")
            return "ok"

        policy = RetryPolicy(
            max_attempts=3, base_delay=0.0,
            on_retry=lambda attempt, exc, delay: events.append((attempt, delay)),
        )
        assert await policy.call(flaky) == "ok"
        assert attempts == 3
        assert [a for a, _ in events] == [1, 2]

    @pytest.mark.asyncio
    async def test_retry_exhausts_and_raises(self):
        """重试耗尽：达到 max_attempts 后抛出最后一次异常。"""
        attempts = 0

        async def always_fail() -> None:
            nonlocal attempts
            attempts += 1
            raise ValueError("一直失败")

        policy = RetryPolicy(max_attempts=2, base_delay=0.0)
        with pytest.raises(ValueError):
            await policy.call(always_fail)
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_non_retryable_exception(self):
        """可重试异常过滤：非指定异常立即抛出，不再重试。"""
        attempts = 0

        async def bad_type() -> None:
            nonlocal attempts
            attempts += 1
            raise TypeError("不可重试")

        policy = RetryPolicy(max_attempts=3, base_delay=0.0,
                             retryable_exceptions=(ValueError,))
        with pytest.raises(TypeError):
            await policy.call(bad_type)
        assert attempts == 1

    def test_exponential_backoff_with_cap(self):
        """指数退避：延迟按 2 的幂增长并受 max_delay 限制。"""
        policy = RetryPolicy(base_delay=0.1, max_delay=0.3)
        assert policy.delay_for(1) == pytest.approx(0.1)
        assert policy.delay_for(2) == pytest.approx(0.2)
        assert policy.delay_for(5) == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_retry_supports_sync_function(self):
        """同步函数：重试策略同样可包装同步可调用对象。"""
        attempts = 0

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("x")
            return "done"

        assert await RetryPolicy(max_attempts=2, base_delay=0.0).call(flaky) == "done"


class TestTimeoutPolicy:
    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self):
        """超时降级：超时后返回配置的降级值而不抛异常。"""
        policy = TimeoutPolicy(0.01, fallback_value="降级值", raise_on_timeout=False)

        async def slow() -> str:
            await asyncio.sleep(0.5)
            return "slow"

        assert await policy.call(slow) == "降级值"

    @pytest.mark.asyncio
    async def test_timeout_raises_agent_error(self):
        """超时异常：默认抛出自定义 AgentTimeoutError。"""
        policy = TimeoutPolicy(0.01)

        async def slow() -> None:
            await asyncio.sleep(0.5)

        with pytest.raises(AgentTimeoutError):
            await policy.call(slow)

    @pytest.mark.asyncio
    async def test_timeout_passes_through_fast_call(self):
        """时限内完成：正常结果原样返回。"""
        policy = TimeoutPolicy(1.0)

        async def fast() -> str:
            return "fast"

        assert await policy.call(fast) == "fast"


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_fallback_chain_order_and_source(self):
        """降级顺序：主级失败后启用备用级，记录来源与降级标记。"""
        chain = FallbackChain([
            ("主模型", lambda: (_ for _ in ()).throw(RuntimeError("主失败"))),
            ("备用模型", lambda: "备用结果"),
        ])
        result = await chain.run()
        assert result.value == "备用结果"
        assert result.source == "备用模型"
        assert result.degraded is True
        assert [a.name for a in result.attempts] == ["主模型", "备用模型"]
        assert result.attempts[0].ok is False

    @pytest.mark.asyncio
    async def test_fallback_first_success_not_degraded(self):
        """首级成功：不发生降级，degraded 为 False。"""
        chain = FallbackChain([("主模型", lambda: "主结果"), ("备用", lambda: "备结果")])
        result = await chain.run()
        assert result.source == "主模型"
        assert result.degraded is False
        assert len(result.attempts) == 1

    @pytest.mark.asyncio
    async def test_fallback_skip_sentinel(self):
        """主动跳过：返回 SKIP 哨兵值的级别被记录为失败并继续下一级。"""
        chain = FallbackChain([
            ("跳过级", lambda: FallbackChain.SKIP),
            ("兜底级", lambda: "兜底"),
        ])
        result = await chain.run()
        assert result.value == "兜底"
        assert result.attempts[0].error == "主动跳过"

    @pytest.mark.asyncio
    async def test_fallback_exhausted(self):
        """降级耗尽：全部失败后抛出 FallbackExhausted 并记录所有尝试。"""
        def boom() -> None:
            raise RuntimeError("boom")

        chain = FallbackChain([("a", boom), ("b", boom)])
        with pytest.raises(FallbackExhausted):
            await chain.run()
        assert len(chain.steps) == 2


class TestIdempotencyGuard:
    @pytest.mark.asyncio
    async def test_concurrent_calls_execute_once(self):
        """并发幂等：同一 key 的 10 个并发调用只真正执行一次。"""
        guard = IdempotencyGuard()
        count = 0

        async def work() -> int:
            nonlocal count
            count += 1
            await asyncio.sleep(0.01)
            return count

        results = await asyncio.gather(*(guard.execute("k", work) for _ in range(10)))
        assert count == 1
        assert results == [1] * 10

    @pytest.mark.asyncio
    async def test_repeat_call_returns_cached(self):
        """重复幂等：顺序重复调用返回缓存结果，不再执行函数。"""
        guard = IdempotencyGuard()
        count = 0

        async def work() -> int:
            nonlocal count
            count += 1
            return count

        assert await guard.execute("k2", work) == 1
        assert await guard.execute("k2", work) == 1
        assert count == 1

    @pytest.mark.asyncio
    async def test_ttl_expiry_reexecutes(self):
        """TTL 过期：缓存过期后重新执行函数。"""
        guard = IdempotencyGuard()
        count = 0

        async def work() -> int:
            nonlocal count
            count += 1
            return count

        await guard.execute("k3", work, ttl=0.01)
        await asyncio.sleep(0.03)
        assert await guard.execute("k3", work, ttl=0.01) == 2
        assert count == 2

    @pytest.mark.asyncio
    async def test_exception_not_cached(self):
        """异常不缓存：失败后再次调用会重新执行。"""
        guard = IdempotencyGuard()
        count = 0

        async def work() -> str:
            nonlocal count
            count += 1
            if count == 1:
                raise ValueError("临时失败")
            return "ok"

        with pytest.raises(ValueError):
            await guard.execute("k4", work)
        assert await guard.execute("k4", work) == "ok"
        assert count == 2


class TestStopConditions:
    def test_max_steps(self):
        """终止条件：达到最大步数触发停止。"""
        decision = StopConditions(max_steps=3).check(steps=3)
        assert decision.should_stop and "最大步数" in decision.reason

    def test_max_duration(self):
        """终止条件：达到最大耗时触发停止。"""
        decision = StopConditions(max_duration=1.5).check(elapsed=1.6)
        assert decision.should_stop and "最大耗时" in decision.reason

    def test_max_tokens(self):
        """终止条件：达到 token 预算触发停止。"""
        decision = StopConditions(max_tokens=100).check(tokens=120)
        assert decision.should_stop and "token" in decision.reason

    def test_max_no_progress(self):
        """终止条件：连续无进展达到阈值触发停止。"""
        decision = StopConditions(max_no_progress=3).check(no_progress=3)
        assert decision.should_stop and "无进展" in decision.reason

    def test_repeat_action(self):
        """终止条件：重复动作达到阈值触发停止。"""
        decision = StopConditions(detect_repeat=True, repeat_threshold=2).check(
            StopState(action="search", history=["search"])
        )
        assert decision.should_stop and "重复动作" in decision.reason

    def test_no_condition_matched(self):
        """未命中：所有条件未触发时返回 should_stop=False。"""
        decision = StopConditions(max_steps=5, detect_repeat=True).check(steps=2, action="a")
        assert decision.should_stop is False
        assert StopConditions().check().should_stop is False


class TestResilienceConfig:
    @pytest.mark.asyncio
    async def test_combines_retry_and_idempotency(self):
        """一站式装配：幂等包裹重试，并发调用只执行一次守卫但内部完成重试。"""
        config = ResilienceConfig(
            retry=RetryPolicy(max_attempts=3, base_delay=0.0),
            idempotency=IdempotencyGuard(),
        )
        count = 0

        async def flaky() -> str:
            nonlocal count
            count += 1
            if count < 3:
                raise ValueError("临时")
            return "ok"

        first, second = await asyncio.gather(
            config.run("rk", flaky), config.run("rk", flaky)
        )
        assert first == second == "ok"
        assert count == 3

    @pytest.mark.asyncio
    async def test_failure_falls_back(self):
        """一站式降级：执行失败且超时重试后仍失败时使用 fallback。"""
        config = ResilienceConfig(retry=RetryPolicy(max_attempts=1, base_delay=0.0))

        async def boom() -> None:
            raise ValueError("boom")

        assert await config.run("fb-key", boom, fallback="兜底") == "兜底"

    @pytest.mark.asyncio
    async def test_timeout_inside_config(self):
        """一站式超时：配置的 TimeoutPolicy 在 run 中生效并返回降级值。"""
        config = ResilienceConfig(
            timeout=TimeoutPolicy(0.01, fallback_value="超时降级", raise_on_timeout=False)
        )

        async def slow() -> str:
            await asyncio.sleep(0.5)
            return "slow"

        assert await config.run("to-key", slow) == "超时降级"

    @pytest.mark.asyncio
    async def test_stop_condition_raises_or_falls_back(self):
        """一站式终止：命中终止条件时抛错或走降级。"""
        config = ResilienceConfig(stop=StopConditions(max_steps=2))

        async def work() -> str:
            return "x"

        with pytest.raises(StopRequestedError):
            await config.run("stop-1", work, stop_state=StopState(steps=2))
        assert await config.run(
            "stop-2", work, fallback="停止降级", stop_state=StopState(steps=3)
        ) == "停止降级"
