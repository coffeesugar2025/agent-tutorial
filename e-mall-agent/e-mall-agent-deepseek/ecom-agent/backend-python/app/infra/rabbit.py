"""RabbitMQ 生产者/消费者（pika 同步版，含 DLX、重试、落库兜底）。

可靠性设计：
1. 交换机 ``ecom.agent``(topic) + 死信 ``ecom.agent.dlx``；每个 routing key 三条队列：
   ``main``（业务）、``main.retry``（TTL 5s 后回投 main）、``main.dead``（死信，3 次后落库）；
2. 发布失败（MQ 未启 / 不可用 / pika 未装）→ 写 ``async_task`` 表（status=QUEUED），
   由 :mod:`app.workers` 的本地 drainer 继续消费，保证业务不中断；
3. 所有消息 ``delivery_mode=2`` 持久化，``confirm_delivery`` 开启 publisher confirm。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models_obs import AsyncTask
from app.obs.metrics import record_degradation

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    import pika
    from pika.exceptions import AMQPError

    PIKA_AVAILABLE = True
except Exception:  # noqa: BLE001
    pika = None  # type: ignore[assignment]
    AMQPError = Exception  # type: ignore[assignment,misc]
    PIKA_AVAILABLE = False

Handler = Callable[[dict[str, Any]], None]

# routing key → 处理器（真实消费者与本地 drainer 共用）
HANDLERS: dict[str, Handler] = {}
RETRY_TTL_MS = 5000
_DOWN_COOLDOWN = 15.0


def register_handler(routing_key: str, handler: Handler) -> None:
    """注册某个 routing key 的处理器（幂等）。"""
    HANDLERS[routing_key] = handler


def queue_name(routing_key: str) -> str:
    return f"{settings.mq_queue_prefix}.{routing_key}"


def retry_queue_name(routing_key: str) -> str:
    return f"{queue_name(routing_key)}.retry"


def dead_queue_name(routing_key: str) -> str:
    return f"{queue_name(routing_key)}.dead"


# ---------------------------------------------------------------------------
# 持久化兜底
# ---------------------------------------------------------------------------
def persist_task(
    task_type: str,
    payload: dict[str, Any],
    status: str = "QUEUED",
    error: str | None = None,
    max_retry: int | None = None,
) -> int:
    """把任务落 ``async_task`` 表，返回主键（失败返回 0，绝不抛）。"""
    try:
        with session_scope() as db:
            row = AsyncTask(
                task_type=task_type,
                payload=payload,
                status=status,
                error=error,
                max_retry=max_retry if max_retry is not None else settings.mq_max_retry,
            )
            db.add(row)
            db.flush()
            return int(row.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("async_task 落库失败 task_type=%s err=%s", task_type, exc)
        return 0


def _update_task_status(task_id: int, status: str, error: str | None = None, retry: int | None = None) -> None:
    if not task_id:
        return
    try:
        with session_scope() as db:
            row = db.get(AsyncTask, task_id)
            if row is None:
                return
            row.status = status
            if error is not None:
                row.error = error[:4000]
            if retry is not None:
                row.retry = retry
    except Exception as exc:  # noqa: BLE001
        logger.warning("async_task 状态更新失败 id=%s err=%s", task_id, exc)


# ---------------------------------------------------------------------------
# 生产者
# ---------------------------------------------------------------------------
class MessageBus:
    """pika 连接/通道复用 + 失败兜底。"""

    def __init__(self) -> None:
        self._conn: Any = None
        self._channel: Any = None
        self._lock = threading.Lock()
        self._down_until = 0.0

    # --- 连接 ---------------------------------------------------------------
    def _params(self) -> Any:
        return pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            virtual_host=settings.rabbitmq_vhost,
            credentials=pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password),
            heartbeat=settings.rabbitmq_heartbeat,
            socket_timeout=3,
            connection_attempts=1,
            blocked_connection_timeout=3,
        )

    def _connect(self) -> Any:
        if not PIKA_AVAILABLE or not settings.mq_enabled:
            return None
        if time.time() < self._down_until:
            return None
        with self._lock:
            if self._channel is not None and getattr(self._channel, "is_open", False):
                return self._channel
            try:
                self._conn = pika.BlockingConnection(self._params())
                channel = self._conn.channel()
                channel.exchange_declare(
                    exchange=settings.mq_exchange, exchange_type="topic", durable=True
                )
                channel.exchange_declare(
                    exchange=settings.mq_dlx_exchange, exchange_type="topic", durable=True
                )
                channel.confirm_delivery()
                self._channel = channel
                logger.info("RabbitMQ 已连接 %s:%s", settings.rabbitmq_host, settings.rabbitmq_port)
                return channel
            except Exception as exc:  # noqa: BLE001
                self._down_until = time.time() + _DOWN_COOLDOWN
                record_degradation("rabbitmq", f"connect:{type(exc).__name__}")
                self._close_locked()
                return None

    def _close_locked(self) -> None:
        for target in (self._channel, self._conn):
            try:
                if target is not None and target.is_open:
                    target.close()
            except Exception:  # noqa: BLE001
                pass
        self._channel = None
        self._conn = None

    # --- 发布 ---------------------------------------------------------------
    def publish(self, routing_key: str, payload: dict[str, Any], task_type: str | None = None) -> bool:
        """发布消息；失败自动落库兜底。返回是否真正投递到 MQ。"""
        task_type = task_type or routing_key
        channel = self._connect()
        if channel is None:
            task_id = persist_task(task_type, payload, status="QUEUED", error="mq_unavailable")
            logger.warning(
                "MQ 不可用，任务已落库 task=%s id=%s payload=%s", task_type, task_id, payload
            )
            return False
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        try:
            properties = pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                headers={"x-task-type": task_type, "x-retry": 0, "x-async-task-id": 0},
            )
            channel.basic_publish(
                exchange=settings.mq_exchange,
                routing_key=routing_key,
                body=body,
                properties=properties,
                mandatory=False,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._down_until = time.time() + _DOWN_COOLDOWN
            record_degradation("rabbitmq", f"publish:{type(exc).__name__}")
            with self._lock:
                self._close_locked()
            task_id = persist_task(task_type, payload, status="QUEUED", error=str(exc))
            logger.warning("MQ 发布失败已落库 task=%s id=%s err=%s", task_type, task_id, exc)
            return False

    async def publish_async(self, routing_key: str, payload: dict[str, Any], task_type: str | None = None) -> bool:
        """异步封装：把阻塞的 pika 调用丢到线程池，避免卡住事件循环。"""
        import asyncio

        return await asyncio.to_thread(self.publish, routing_key, payload, task_type)

    def health(self) -> str:
        if not settings.mq_enabled:
            return "DISABLED"
        if not PIKA_AVAILABLE:
            return "DOWN"
        return "UP" if self._connect() is not None else "DOWN"

    def reset(self) -> None:
        with self._lock:
            self._down_until = 0.0
            self._close_locked()

    def close(self) -> None:
        with self._lock:
            self._close_locked()


message_bus = MessageBus()


# ---------------------------------------------------------------------------
# 本地 drainer：MQ 不可用时消费 async_task
# ---------------------------------------------------------------------------
def dispatch_local(routing_key: str, payload: dict[str, Any]) -> None:
    """直接调用本地处理器（失败抛出，由调用方决定重试）。"""
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise KeyError(f"未注册的 routing key: {routing_key}")
    handler(payload)


def drain_pending_tasks(limit: int = 10) -> int:
    """消费 ``async_task`` 中 QUEUED/FAILED 的任务，返回成功条数。"""
    if not HANDLERS:
        return 0
    with session_scope() as db:
        rows = (
            db.query(AsyncTask)
            .filter(AsyncTask.status.in_(["QUEUED", "FAILED"]))
            .order_by(AsyncTask.id.asc())
            .limit(limit)
            .all()
        )
        tasks = [(row.id, row.task_type, row.payload or {}, row.retry, row.max_retry) for row in rows]
    succeeded = 0
    for task_id, task_type, payload, retry, max_retry in tasks:
        routing_key = task_type
        if routing_key not in HANDLERS:
            _update_task_status(task_id, "DEAD", f"no handler for {routing_key}")
            continue
        _update_task_status(task_id, "RUNNING")
        try:
            dispatch_local(routing_key, payload)
        except Exception as exc:  # noqa: BLE001
            next_retry = retry + 1
            status = "DEAD" if next_retry >= max_retry else "FAILED"
            _update_task_status(task_id, status, str(exc), retry=next_retry)
            logger.warning("本地任务失败 task=%s retry=%s status=%s err=%s", task_type, next_retry, status, exc)
        else:
            _update_task_status(task_id, "SUCCESS")
            succeeded += 1
    return succeeded


# ---------------------------------------------------------------------------
# 真实消费者
# ---------------------------------------------------------------------------
class QueueConsumer:
    """pika 消费者：声明 main/retry/dead 三队列，手动 ack，异常重试。"""

    def __init__(self) -> None:
        self._conn: Any = None
        self._channel: Any = None
        self._stop = threading.Event()

    def _declare(self, channel: Any, routing_key: str) -> str:
        main_queue = queue_name(routing_key)
        retry_queue = retry_queue_name(routing_key)
        dead_queue = dead_queue_name(routing_key)
        channel.exchange_declare(exchange=settings.mq_exchange, exchange_type="topic", durable=True)
        channel.exchange_declare(exchange=settings.mq_dlx_exchange, exchange_type="topic", durable=True)
        # 死信队列
        channel.queue_declare(queue=dead_queue, durable=True)
        channel.queue_bind(queue=dead_queue, exchange=settings.mq_dlx_exchange, routing_key=routing_key)
        # 重试队列：TTL 到期后回投主交换机
        channel.queue_declare(
            queue=retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": RETRY_TTL_MS,
                "x-dead-letter-exchange": settings.mq_exchange,
                "x-dead-letter-routing-key": routing_key,
            },
        )
        # 主队列
        channel.queue_declare(
            queue=main_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.mq_dlx_exchange,
                "x-dead-letter-routing-key": routing_key,
            },
        )
        channel.queue_bind(queue=main_queue, exchange=settings.mq_exchange, routing_key=routing_key)
        return main_queue

    def start(self, routing_keys: list[str] | None = None) -> None:
        """阻塞式启动（在独立线程里调用）；pika 缺失时直接告警返回。"""
        if not PIKA_AVAILABLE or not settings.mq_enabled:
            logger.warning("pika 未安装或 MQ 未启用，消费者不启动（依赖本地 drainer 兜底）")
            return
        keys = routing_keys or list(HANDLERS.keys())
        if not keys:
            logger.warning("没有注册任何 routing key，消费者不启动")
            return
        try:
            self._conn = pika.BlockingConnection(message_bus._params())
            channel = self._conn.channel()
            channel.basic_qos(prefetch_count=4)
            for routing_key in keys:
                queue = self._declare(channel, routing_key)
                channel.basic_consume(
                    queue=queue,
                    on_message_callback=self._make_callback(routing_key),
                    auto_ack=False,
                )
            self._channel = channel
            logger.info("消费者已启动 queues=%s", [queue_name(k) for k in keys])
            while not self._stop.is_set():
                self._conn.process_data_events(time_limit=1)
        except Exception as exc:  # noqa: BLE001
            record_degradation("rabbitmq", f"consume:{type(exc).__name__}")
            logger.error("消费者异常退出: %s", exc)
        finally:
            self._shutdown()

    def _make_callback(self, routing_key: str) -> Callable[[Any, Any, Any, bytes], None]:
        def _callback(ch: Any, method: Any, properties: Any, body: bytes) -> None:
            headers = (properties.headers or {}) if properties else {}
            retry = int(headers.get("x-retry", 0) or 0)
            task_id = int(headers.get("x-async-task-id", 0) or 0)
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.error("消息体解析失败 rk=%s err=%s", routing_key, exc)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            if task_id:
                _update_task_status(task_id, "RUNNING")
            try:
                dispatch_local(routing_key, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("消费失败 rk=%s retry=%s err=%s", routing_key, retry, exc)
                self._requeue(ch, routing_key, payload, properties, retry, task_id, exc)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            if task_id:
                _update_task_status(task_id, "SUCCESS")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        return _callback

    def _requeue(
        self,
        channel: Any,
        routing_key: str,
        payload: dict[str, Any],
        properties: Any,
        retry: int,
        task_id: int,
        exc: Exception,
    ) -> None:
        next_retry = retry + 1
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        if next_retry >= settings.mq_max_retry:
            channel.basic_publish(
                exchange=settings.mq_dlx_exchange,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    headers={"x-task-type": routing_key, "x-retry": next_retry, "x-async-task-id": task_id},
                ),
            )
            _update_task_status(task_id, "DEAD", str(exc), retry=next_retry)
            return
        channel.basic_publish(
            exchange="",
            routing_key=retry_queue_name(routing_key),
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                headers={"x-task-type": routing_key, "x-retry": next_retry, "x-async-task-id": task_id},
            ),
        )
        _update_task_status(task_id, "QUEUED", str(exc), retry=next_retry)

    def stop(self) -> None:
        self._stop.set()

    def _shutdown(self) -> None:
        for target in (self._channel, self._conn):
            try:
                if target is not None and target.is_open:
                    target.close()
            except Exception:  # noqa: BLE001
                pass
        self._channel = None
        self._conn = None


__all__ = [
    "HANDLERS",
    "Handler",
    "MessageBus",
    "PIKA_AVAILABLE",
    "QueueConsumer",
    "dead_queue_name",
    "dispatch_local",
    "drain_pending_tasks",
    "message_bus",
    "persist_task",
    "queue_name",
    "register_handler",
    "retry_queue_name",
]
