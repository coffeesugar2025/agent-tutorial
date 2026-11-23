"""消息队列消费者与 handler 注册。"""

from app.mq.consumers import register_all

__all__ = ["register_all"]
