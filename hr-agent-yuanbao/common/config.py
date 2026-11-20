"""集中配置：所有可调参数都在这里，改环境变量即可，不用翻代码。"""
from __future__ import annotations

import os
from pathlib import Path

# 可选：若装了 python-dotenv 就自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # 没装也能跑
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HANDBOOK_DIR = DATA_DIR / "handbook"
DB_PATH = DATA_DIR / "hr_agent.db"
VECTOR_PATH = DATA_DIR / "vectors.json"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

FORCE_MOCK = os.getenv("HR_AGENT_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}
MAX_STEPS = int(os.getenv("HR_AGENT_MAX_STEPS", "8"))
TOKEN_BUDGET = int(os.getenv("HR_AGENT_TOKEN_BUDGET", "3000"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HANDBOOK_DIR.mkdir(parents=True, exist_ok=True)
