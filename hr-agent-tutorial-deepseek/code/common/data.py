"""HR 种子数据加载器。

所有数据都是虚构的，仅用于教学。统一从 code/data 目录读取，避免每个章节各自造数据。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = CODE_DIR / "data"
POLICY_DIR = DATA_DIR / "policies"


@lru_cache(maxsize=64)
def load_json(name: str) -> list | dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=64)
def load_text(name: str) -> str:
    return (DATA_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def employees() -> list[dict]:
    return load_json("employees.json")


@lru_cache(maxsize=1)
def candidates() -> list[dict]:
    return load_json("candidates.json")


@lru_cache(maxsize=1)
def tickets() -> list[dict]:
    return load_json("tickets.json")


@lru_cache(maxsize=1)
def org() -> dict:
    return load_json("org.json")


def employee(employee_id: str) -> dict | None:
    return next((item for item in employees() if item["id"] == employee_id), None)


def employee_by_name(name: str) -> dict | None:
    return next((item for item in employees() if item["name"] == name), None)


def candidate(candidate_id: str) -> dict | None:
    return next((item for item in candidates() if item["id"] == candidate_id), None)


@lru_cache(maxsize=1)
def policy_manifest() -> list[dict]:
    return load_json("policies/manifest.json")


def policy_document(doc_id: str) -> dict | None:
    """返回带正文的制度文档。"""
    for item in policy_manifest():
        if item["doc_id"] == doc_id:
            return {**item, "content": (POLICY_DIR / item["file"]).read_text(encoding="utf-8")}
    return None


def all_policy_documents() -> list[dict]:
    return [{**item, "content": (POLICY_DIR / item["file"]).read_text(encoding="utf-8")} for item in policy_manifest()]
