"""线程安全的版本化 Prompt 注册中心。

支持按名称 + 版本注册模板、渲染、切换活跃版本；变量从模板自动抽取，也允许
显式声明。可从 ``specialists.PERSONAS`` 只读初始化，不修改源文件。
"""
from __future__ import annotations

import re
import threading
from string import Formatter
from typing import Any, Mapping

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """一条版本化 Prompt 模板。"""

    name: str
    version: str
    template: str
    variables: list[str] = Field(default_factory=list)


def _extract_variables(template: str) -> list[str]:
    """从模板中抽取 ``{var}`` 占位符；忽略格式说明中的字段名。"""
    found: list[str] = []
    for _, field_name, _, _ in Formatter().parse(template or ""):
        if not field_name:
            continue
        root = re.split(r"[.\[]", field_name, maxsplit=1)[0]
        if root and root not in found:
            found.append(root)
    return found


def _version_key(version: str) -> list[Any]:
    """版本自然排序键：v2 排在 v10 之前。"""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", version) if part]


class PromptRegistry:
    """内存版 Prompt 注册中心，所有操作受 RLock 保护。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, dict[str, PromptTemplate]] = {}
        self._active: dict[str, str] = {}

    def register(
        self,
        name: str,
        version: str,
        template: str,
        variables: list[str] | None = None,
    ) -> PromptTemplate:
        """注册一个版本；首次注册自动成为活跃版本。"""
        if not name or not version:
            raise ValueError("name 与 version 不能为空")
        item = PromptTemplate(
            name=name,
            version=version,
            template=template,
            variables=list(variables) if variables is not None else _extract_variables(template),
        )
        with self._lock:
            self._store.setdefault(name, {})[version] = item
            self._active.setdefault(name, version)
            return item

    def get(self, name: str, version: str | None = None) -> PromptTemplate:
        """取指定版本模板；version 为 None 时取活跃版本。"""
        with self._lock:
            versions = self._store.get(name)
            if not versions:
                raise KeyError(f"未注册的 Prompt: {name}")
            target = version or self._active.get(name)
            if target not in versions:
                raise KeyError(f"Prompt {name} 不存在版本 {target!r}")
            return versions[target]

    def render(self, name: str, version: str | None = None, /, **vars: Any) -> str:
        """渲染模板；缺少必需变量时抛 KeyError。

        前两个参数设为位置限定，避免模板变量恰好叫 ``name`` / ``version``
        时与函数参数冲突。
        """
        item = self.get(name, version)
        missing = [var for var in item.variables if var not in vars]
        if missing:
            raise KeyError(f"Prompt {name}@{item.version} 缺少变量: {', '.join(missing)}")
        try:
            return item.template.format(**vars)
        except KeyError as exc:
            raise KeyError(f"Prompt {name}@{item.version} 缺少变量: {exc}") from exc

    def list_versions(self, name: str) -> list[str]:
        """按自然排序列出某 Prompt 的全部版本。"""
        with self._lock:
            return sorted(self._store.get(name, {}), key=_version_key)

    def set_active(self, name: str, version: str) -> None:
        """切换活跃版本；版本不存在时抛 KeyError。"""
        with self._lock:
            if version not in self._store.get(name, {}):
                raise KeyError(f"Prompt {name} 不存在版本 {version!r}")
            self._active[name] = version

    def get_active_version(self, name: str) -> str:
        """读取当前活跃版本号。"""
        with self._lock:
            version = self._active.get(name)
            if version is None:
                raise KeyError(f"未注册的 Prompt: {name}")
            return version

    def init_from_personas(
        self, personas: Mapping[str, str] | None = None, version: str = "v1"
    ) -> int:
        """从 ``specialists.PERSONAS`` 只读初始化，返回新增条数。"""
        if personas is None:
            from ..agents.specialists import PERSONAS  # 只读导入

            personas = PERSONAS
        added = 0
        with self._lock:
            for name, text in personas.items():
                if version not in self._store.get(name, {}):
                    self.register(name, version, text)
                    added += 1
        return added


default_registry = PromptRegistry()

register = default_registry.register
render = default_registry.render
list_versions = default_registry.list_versions
set_active = default_registry.set_active
init_from_personas = default_registry.init_from_personas
