"""Golden test cases and JSON-serialisable datasets."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class GoldenCase:
    """One labelled evaluation case.

    ``expected`` describes the assertion(s); see :mod:`app.eval.evaluator` for
    the supported scorer names.
    """

    id: str
    name: str = ""
    input: Any = ""
    expected: Any = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "input": self.input,
            "expected": self.expected, "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenCase":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            input=data.get("input", ""),
            expected=data.get("expected"),
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
        )


class CaseDataset:
    """Ordered collection of :class:`GoldenCase` with tag filtering."""

    def __init__(self, cases: list[GoldenCase] | None = None) -> None:
        self.cases: list[GoldenCase] = list(cases or [])

    def add(self, case: GoldenCase) -> "CaseDataset":
        self.cases.append(case)
        return self

    def filter_by_tag(self, tag: str | list[str]) -> "CaseDataset":
        wanted = {tag} if isinstance(tag, str) else set(tag)
        return CaseDataset([
            case for case in self.cases if wanted.intersection(case.tags)
        ])

    def __iter__(self) -> Iterator[GoldenCase]:
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "cases": [c.to_dict() for c in self.cases]}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseDataset":
        return cls([GoldenCase.from_dict(item)
                    for item in data.get("cases", [])])

    @classmethod
    def from_json(cls, text: str) -> "CaseDataset":
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "CaseDataset":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


__all__ = ["GoldenCase", "CaseDataset"]
