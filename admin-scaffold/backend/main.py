"""
兼容入口：允许在 backend/ 目录下直接执行 `uvicorn main:app --reload`。

项目本体是包结构，规范入口为 `uvicorn app.main:app --reload`；
本文件只是把 app.main 里的 FastAPI 实例重新导出，两种写法等价。
注意：必须 cd 到 backend/ 目录运行，否则 `scripts.seed` 等相对导入会找不到。
"""
from app.main import app  # noqa: F401

__all__ = ["app"]
