"""Skill 渐进式披露加载器：``SKILL.md`` frontmatter → 正文 → 资源清单。

三层披露（对 prompt 成本的直接控制）：

1. **Layer 1 · metadata**：只解析 ``SKILL.md`` 的 YAML frontmatter（name/description/
   tags/triggers/allowedTools/maxSteps），用于向模型展示"有哪些 Skill、何时用"；
2. **Layer 2 · body**：只有真正命中某个 Skill 时才读取 Markdown 正文（执行步骤、
   话术、禁止事项），并可按字符预算截断；
3. **Layer 3 · resources**：正文里引用的模板/表格/示例放在同目录的其它文件里，
   先 :meth:`SkillLoader.list_resources` 列清单，再 :meth:`SkillLoader.read_resource`
   按需读取（带目录穿越防护与大小上限）。

依赖策略：仅用标准库；``PyYAML`` 存在时用 ``yaml.safe_load``，否则走内置的
极简 frontmatter 解析器（支持 ``key: value``、``key: [a, b]`` 与 ``- item`` 列表）。
目录不存在、单个 Skill 解析失败都只记日志并跳过，**不会让 import 或调用失败**。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
FRONTMATTER_RE = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_CAMEL_TO_SNAKE_RE = re.compile(r"([a-z0-9])([A-Z])")

_KIND_BY_SUFFIX: dict[str, str] = {
    ".md": "text",
    ".markdown": "text",
    ".txt": "text",
    ".json": "text",
    ".jsonl": "text",
    ".yaml": "text",
    ".yml": "text",
    ".csv": "text",
    ".html": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".pdf": "binary",
}

DEFAULT_BODY_BUDGET = 4000
DEFAULT_RESOURCE_BYTES = 200_000


class SkillError(RuntimeError):
    """Skill 加载/读取错误基类。"""


class SkillNotFound(SkillError):
    """Skill 不存在（目录或名称不匹配）。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class SkillMeta:
    """Layer 1：只含元信息，不含正文。"""

    name: str
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    max_steps: int | None = None
    path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "triggers": list(self.triggers),
            "allowedTools": list(self.allowed_tools),
            "maxSteps": self.max_steps,
            "path": str(self.path) if self.path else None,
            "extra": dict(self.extra),
        }


@dataclass
class Skill:
    """某个 Skill 的完整视图（``body`` 为空表示尚未加载正文）。"""

    meta: SkillMeta
    body: str = ""
    resources: list[dict[str, Any]] = field(default_factory=list)
    body_loaded: bool = False

    @property
    def name(self) -> str:
        return self.meta.name

    def to_dict(self, *, include_body: bool = False) -> dict[str, Any]:
        payload = self.meta.to_dict()
        payload["bodyLoaded"] = self.body_loaded
        payload["resources"] = list(self.resources)
        if include_body:
            payload["body"] = self.body
        return payload


# ---------------------------------------------------------------------------
# frontmatter 解析
# ---------------------------------------------------------------------------
def split_frontmatter(text: str) -> tuple[str, str]:
    """拆出 ``(frontmatter, body)``；没有 frontmatter 时返回 ``("", 原文)``。"""
    if not text:
        return "", ""
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return "", text
    header = match.group(1) or ""
    body = text[match.end() :]
    return header, body.lstrip("\r\n")


def _parse_scalar(raw: str) -> Any:
    """标量解析：引号字符串 / bool / int / float / 内联列表。"""
    value = raw.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",") if part.strip()]
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _normalize_key(key: str) -> str:
    """``allowedTools`` / ``allowed-tools`` → ``allowed_tools``。"""
    snake = _CAMEL_TO_SNAKE_RE.sub(r"\1_\2", key.strip())
    return snake.replace("-", "_").lower()


def _simple_parse_yaml(block: str) -> dict[str, Any]:
    """极简 YAML 子集解析（无 PyYAML 时的兜底）。"""
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- ") and current_key is not None:
            bucket = result.get(current_key)
            if not isinstance(bucket, list):
                bucket = []
                result[current_key] = bucket
            bucket.append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current_key = _normalize_key(key)
        if value.strip():
            result[current_key] = _parse_scalar(value)
        else:
            result[current_key] = []
    return result


def parse_frontmatter(block: str) -> dict[str, Any]:
    """优先 PyYAML，缺失/失败时回退内置解析器。"""
    if not block.strip():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]

        loaded = yaml.safe_load(block)
        if isinstance(loaded, dict):
            return {_normalize_key(str(key)): value for key, value in loaded.items()}
    except Exception:  # noqa: BLE001 - 无 PyYAML 或内容非法都走兜底
        pass
    return _simple_parse_yaml(block)


def _as_list(value: Any) -> list[str]:
    """把 str / list / tuple 统一为去空白的字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;；\n]", value) if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 加载器
# ---------------------------------------------------------------------------
class SkillLoader:
    """按目录扫描 Skill，并缓存 metadata（正文每次按需读取）。"""

    def __init__(self, root: str | Path | None = None, *, cache: bool = True) -> None:
        self._explicit_root = Path(root) if root else None
        self._cache_enabled = cache
        self._meta_cache: dict[str, tuple[float, SkillMeta]] = {}
        self._body_cache: dict[str, tuple[float, str]] = {}
        self._aliases: dict[str, str] = {}

    # --- 路径 ------------------------------------------------------------
    @property
    def root(self) -> Path:
        if self._explicit_root is None:
            return Path(settings.skills_path)
        path = self._explicit_root
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def _skill_dirs(self) -> list[Path]:
        root = self.root
        if not root.is_dir():
            return []
        if (root / SKILL_FILE).is_file():
            return [root]
        return sorted(
            (path for path in root.iterdir() if path.is_dir() and (path / SKILL_FILE).is_file()),
            key=lambda path: path.name,
        )

    def _find_dir(self, name: str) -> Path | None:
        target = (name or "").strip()
        if not target:
            return None
        for directory in self._skill_dirs():
            resolved = self._aliases.get(target)
            if directory.name == target or resolved == directory.name:
                return directory
        # 别名命中：先刷新一次索引
        self.discover(refresh=True)
        resolved = self._aliases.get(target)
        if resolved:
            for directory in self._skill_dirs():
                if directory.name == resolved:
                    return directory
        return None

    # --- 元信息 ----------------------------------------------------------
    def _read_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8-sig", errors="replace")

    def _parse_meta(self, directory: Path) -> SkillMeta | None:
        skill_file = directory / SKILL_FILE
        try:
            text = self._read_file(skill_file)
        except OSError as exc:  # noqa: BLE001
            logger.warning("读取 %s 失败，跳过: %s", skill_file, exc)
            return None
        header, _ = split_frontmatter(text)
        metadata = parse_frontmatter(header)
        dir_name = directory.name
        name = str(metadata.get("name") or dir_name).strip() or dir_name
        extra = {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "name",
                "description",
                "version",
                "tags",
                "triggers",
                "allowed_tools",
                "max_steps",
            }
        }
        return SkillMeta(
            name=name,
            description=str(metadata.get("description") or "").strip(),
            version=str(metadata.get("version") or "1.0.0"),
            tags=_as_list(metadata.get("tags")),
            triggers=_as_list(metadata.get("triggers")),
            allowed_tools=_as_list(metadata.get("allowed_tools")),
            max_steps=_to_int(metadata.get("max_steps")),
            path=directory,
            extra=extra,
        )

    def discover(self, *, refresh: bool = False) -> list[SkillMeta]:
        """Layer 1：返回全部 Skill 的元信息（按目录名排序，mtime 缓存）。"""
        directories = self._skill_dirs()
        metas: list[SkillMeta] = []
        aliases: dict[str, str] = {}
        for directory in directories:
            skill_file = directory / SKILL_FILE
            try:
                mtime = skill_file.stat().st_mtime
            except OSError:
                continue
            cache_key = directory.name
            cached = self._meta_cache.get(cache_key)
            if self._cache_enabled and not refresh and cached and cached[0] == mtime:
                meta = cached[1]
            else:
                meta = self._parse_meta(directory)
                if meta is None:
                    continue
                if self._cache_enabled:
                    self._meta_cache[cache_key] = (mtime, meta)
            metas.append(meta)
            aliases[meta.name] = directory.name
            aliases[directory.name] = directory.name
        self._aliases = aliases
        return metas

    def list_skills(self) -> list[dict[str, Any]]:
        """Layer 1 的 JSON 视图（可直接给 API / 前端展示）。"""
        return [meta.to_dict() for meta in self.discover()]

    def get(self, name: str, *, load_body: bool = False) -> Skill:
        """取单个 Skill；``load_body=True`` 时才读正文（Layer 2）。"""
        meta = self._meta(name)
        skill = Skill(meta=meta, resources=self.list_resources(name))
        if load_body:
            skill.body = self.load_body(name)
            skill.body_loaded = True
        return skill

    def _meta(self, name: str) -> SkillMeta:
        for meta in self.discover():
            if meta.name == name or (meta.path is not None and meta.path.name == name):
                return meta
        directory = self._find_dir(name)
        if directory is not None:
            meta = self._parse_meta(directory)
            if meta is not None:
                return meta
        available = ", ".join(sorted(meta.name for meta in self.discover())) or "（无）"
        raise SkillNotFound(f"未找到 Skill {name!r}；可用: {available}")

    # --- 正文 ------------------------------------------------------------
    def load_body(self, name: str) -> str:
        """Layer 2：读取技能正文（按 mtime 缓存）。"""
        meta = self._meta(name)
        directory = meta.path or self._find_dir(name)
        if directory is None:
            raise SkillNotFound(f"Skill {name!r} 缺少目录")
        skill_file = directory / SKILL_FILE
        try:
            mtime = skill_file.stat().st_mtime
        except OSError as exc:
            raise SkillNotFound(f"Skill {name!r} 的 {SKILL_FILE} 不可读: {exc}") from exc
        cached = self._body_cache.get(meta.name)
        if self._cache_enabled and cached and cached[0] == mtime:
            return cached[1]
        text = self._read_file(skill_file)
        _, body = split_frontmatter(text)
        body = body.strip()
        if self._cache_enabled:
            self._body_cache[meta.name] = (mtime, body)
        return body

    # --- 资源 ------------------------------------------------------------
    def list_resources(self, name: str) -> list[dict[str, Any]]:
        """Layer 3：资源清单（不含文件内容）。"""
        meta = self._meta(name)
        directory = meta.path or self._find_dir(name)
        if directory is None or not directory.is_dir():
            return []
        resources: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == SKILL_FILE:
                continue
            relative = path.relative_to(directory).as_posix()
            if any(part.startswith(".") for part in relative.split("/")):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            resources.append(
                {
                    "path": relative,
                    "size": int(stat.st_size),
                    "kind": _KIND_BY_SUFFIX.get(path.suffix.lower(), "binary"),
                    "modifiedAt": int(stat.st_mtime),
                }
            )
        return resources

    def read_resource(self, name: str, relative: str, *, max_bytes: int = DEFAULT_RESOURCE_BYTES) -> str:
        """Layer 3：读取单个资源文本（目录穿越 / 超大文件都被拒绝）。"""
        meta = self._meta(name)
        directory = meta.path or self._find_dir(name)
        if directory is None:
            raise SkillNotFound(f"Skill {name!r} 缺少目录")
        base = directory.resolve()
        target = (directory / relative).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise SkillError(f"非法的资源路径: {relative}") from exc
        if target.name == SKILL_FILE:
            return self.load_body(name)
        if not target.is_file():
            raise SkillError(f"资源不存在: {relative}")
        size = target.stat().st_size
        if max_bytes > 0 and size > max_bytes:
            logger.warning("资源 %s/%s 大小 %s 超过上限 %s，已截断", name, relative, size, max_bytes)
            with target.open("rb") as handle:
                data = handle.read(max_bytes)
            return data.decode("utf-8", errors="replace")
        return target.read_text(encoding="utf-8", errors="replace")

    # --- 匹配与提示词 ----------------------------------------------------
    def match(self, query: str, *, limit: int = 3) -> list[SkillMeta]:
        """按 triggers / tags / name / description 做确定性匹配（用于路由提示）。"""
        text = (query or "").strip()
        if not text:
            return []
        lowered = text.lower()
        scored: list[tuple[int, str, SkillMeta]] = []
        for meta in self.discover():
            score = 0
            for trigger in meta.triggers:
                if trigger and trigger in text:
                    score += 3
            for tag in meta.tags:
                if tag and tag.lower() in lowered:
                    score += 2
            if meta.name and (meta.name in text or meta.name.lower() in lowered):
                score += 2
            for word in re.split(r"[\s,，。；;、/]+", meta.description):
                if len(word) >= 2 and word in text:
                    score += 1
            if score > 0:
                scored.append((score, meta.name, meta))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [meta for _, _, meta in scored[: max(limit, 1)]]

    def index_block(self, *, limit: int = 20, description_chars: int = 160) -> str:
        """Layer 1 提示词块：只含名称、描述、可用工具。"""
        metas = self.discover()[: max(limit, 0)]
        if not metas:
            return ""
        lines = ["【可用 Skill】命中以下场景时先加载对应 Skill 正文，不要臆测其中的规则："]
        for meta in metas:
            description = meta.description[:description_chars]
            suffix = f"（工具: {', '.join(meta.allowed_tools)}）" if meta.allowed_tools else ""
            lines.append(f"- {meta.name}: {description}{suffix}")
        return "\n".join(lines)

    def prompt_block(
        self,
        names: list[str] | None = None,
        *,
        include_body: bool = False,
        max_chars: int = DEFAULT_BODY_BUDGET,
    ) -> str:
        """按需拼装 Skill 提示词（Layer 1 + 可选 Layer 2），受字符预算约束。"""
        metas = self.discover()
        if names:
            wanted = set(names)
            metas = [meta for meta in metas if meta.name in wanted or (meta.path and meta.path.name in wanted)]
        if not metas:
            return ""
        blocks: list[str] = [self.index_block()] if not names else []
        used = sum(len(block) for block in blocks)
        for meta in metas:
            header = f"## {meta.name}\n{meta.description}".strip()
            if include_body:
                try:
                    body = self.load_body(meta.name)
                except SkillError as exc:  # noqa: BLE001 - 单个技能失败不影响其它
                    logger.warning("加载 Skill 正文失败 %s: %s", meta.name, exc)
                    body = ""
                header = f"{header}\n\n{body}" if body else header
            if used + len(header) > max_chars:
                blocks.append(f"## {meta.name}\n{meta.description[:200]}（正文超预算，按需再加载）")
                break
            blocks.append(header)
            used += len(header)
        return "\n\n".join(block for block in blocks if block)

    def reload(self) -> None:
        """清空缓存（技能文件热更新后调用）。"""
        self._meta_cache.clear()
        self._body_cache.clear()
        self._aliases.clear()

    def describe(self) -> dict[str, Any]:
        """调试视图：根目录、技能数、每个技能的元信息与资源。"""
        metas = self.discover()
        return {
            "root": str(self.root),
            "exists": self.root.is_dir(),
            "count": len(metas),
            "skills": [
                {**meta.to_dict(), "resources": [item["path"] for item in self.list_resources(meta.name)]}
                for meta in metas
            ],
        }


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def get_loader(root: str | None = None) -> SkillLoader:
    """进程级加载器（按 root 缓存）。"""
    return SkillLoader(root)


def reset_loader() -> None:
    """测试/热更新用：清空全局加载器。"""
    get_loader.cache_clear()


def list_skills(root: str | None = None) -> list[dict[str, Any]]:
    """列出全部 Skill 的元信息。"""
    return get_loader(root).list_skills()


def load_skill(name: str, *, root: str | None = None, include_body: bool = True) -> dict[str, Any]:
    """加载单个 Skill（默认带正文），返回可 JSON 序列化的 dict。"""
    return get_loader(root).get(name, load_body=include_body).to_dict(include_body=include_body)


def skill_index(root: str | None = None) -> str:
    """Layer 1 提示词块。"""
    return get_loader(root).index_block()


def load_skill_prompt(
    names: list[str] | None = None,
    *,
    root: str | None = None,
    include_body: bool = True,
    max_chars: int = DEFAULT_BODY_BUDGET,
) -> str:
    """按需生成 Skill 提示词（配合 runtime 的 system prompt 使用）。"""
    return get_loader(root).prompt_block(names, include_body=include_body, max_chars=max_chars)


__all__ = [
    "DEFAULT_BODY_BUDGET",
    "DEFAULT_RESOURCE_BYTES",
    "FRONTMATTER_RE",
    "SKILL_FILE",
    "Skill",
    "SkillError",
    "SkillLoader",
    "SkillMeta",
    "SkillNotFound",
    "get_loader",
    "list_skills",
    "load_skill",
    "load_skill_prompt",
    "parse_frontmatter",
    "reset_loader",
    "skill_index",
    "split_frontmatter",
]
