"""基础设施配置：全部通过 ECOM_* 环境变量启用。

刻意不依赖 app/config.py（pydantic-settings），保持纯标准库，便于测试用
monkeypatch 精确控制环境变量。空 URL / 空 key 表示“未配置”，各适配器会自动
回退到现有内存或离线实现，保证零配置启动与测试不受影响。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class InfraSettings:
    """生产基础设施连接参数与模型清单。"""

    mysql_url: str = ""
    redis_url: str = ""
    rabbitmq_url: str = ""
    milvus_url: str = ""
    milvus_token: str = ""

    llm_providers: str = "offline"
    llm_default_provider: str = "offline"
    deepseek_api_key: str = ""
    qwen_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @classmethod
    def from_env(cls) -> "InfraSettings":
        """每次调用都重新读取环境变量（不缓存），便于测试与热加载。"""
        return cls(
            mysql_url=os.getenv("ECOM_MYSQL_URL", ""),
            redis_url=os.getenv("ECOM_REDIS_URL", ""),
            rabbitmq_url=os.getenv("ECOM_RABBITMQ_URL", ""),
            milvus_url=os.getenv("ECOM_MILVUS_URL", ""),
            milvus_token=os.getenv("ECOM_MILVUS_TOKEN", ""),
            llm_providers=os.getenv("ECOM_LLM_PROVIDERS", "offline"),
            llm_default_provider=os.getenv("ECOM_LLM_DEFAULT_PROVIDER", "offline"),
            deepseek_api_key=os.getenv("ECOM_DEEPSEEK_API_KEY", ""),
            qwen_api_key=os.getenv("ECOM_QWEN_API_KEY", ""),
            deepseek_base_url=os.getenv(
                "ECOM_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            qwen_base_url=os.getenv(
                "ECOM_QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )

    @property
    def provider_names(self) -> list[str]:
        """解析逗号分隔的模型供应商清单，去空、去重并保持顺序。"""
        names: list[str] = []
        for raw in self.llm_providers.split(","):
            name = raw.strip().lower()
            if name and name not in names:
                names.append(name)
        return names or ["offline"]
