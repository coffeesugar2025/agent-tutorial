"""完整轨迹落盘 + 确定性重放 + 时间旅行（总纲 5.6，工程效率的分水岭）。

与 observability.EvalSuite.replay 的区别：那个是「录制答案重放打分」，
本模块是「固定外部依赖返回值，重跑同一条 Agent 轨迹」。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Frame:
    index: int
    kind: str                 # model | tool | retrieval | decision | human
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    at: float = field(default_factory=time.time)
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "kind": self.kind, "name": self.name,
                "inputs": self.inputs, "outputs": self.outputs,
                "at": self.at, "context_snapshot": self.context_snapshot}


@dataclass
class Trajectory:
    trace_id: str
    question: str
    frames: list[Frame] = field(default_factory=list)
    prompt_version: str = ""
    model_pin: str = ""
    created_at: float = field(default_factory=time.time)

    def digest(self) -> str:
        # digest 只覆盖语义信息；时间/上下文快照不进哈希，否则「确定性重放」永远不相等
        raw = json.dumps({"q": self.question,
                          "frames": [{"index": f.index, "kind": f.kind, "name": f.name,
                                      "inputs": f.inputs, "outputs": f.outputs}
                                     for f in self.frames],
                          "prompt": self.prompt_version, "model": self.model_pin},
                         ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "question": self.question,
                "prompt_version": self.prompt_version, "model_pin": self.model_pin,
                "digest": self.digest(), "frames": [f.to_dict() for f in self.frames]}


class TrajectoryStore:
    def __init__(self) -> None:
        self._data: dict[str, Trajectory] = {}
        self._lock = threading.RLock()

    def save(self, t: Trajectory) -> str:
        with self._lock:
            self._data[t.trace_id] = t
            return t.trace_id

    def load(self, trace_id: str) -> Trajectory | None:
        with self._lock:
            return self._data.get(trace_id)

    def compare(self, a_id: str, b_id: str) -> dict[str, Any]:
        a, b = self.load(a_id), self.load(b_id)
        if not a or not b:
            return {"ok": False, "error": "轨迹不存在"}
        diffs = []
        for i in range(max(len(a.frames), len(b.frames))):
            fa = a.frames[i].to_dict() if i < len(a.frames) else None
            fb = b.frames[i].to_dict() if i < len(b.frames) else None
            if fa != fb:
                diffs.append({"index": i, "before": fa, "after": fb})
        return {"ok": True, "identical": not diffs, "diff_count": len(diffs),
                "digest_before": a.digest(), "digest_after": b.digest(),
                "prompt_changed": a.prompt_version != b.prompt_version, "diffs": diffs[:10]}


STORE = TrajectoryStore()


def record(question: str, steps: list[tuple[str, str, Callable[[], dict[str, Any]]]],
           prompt_version: str = "v1", model_pin: str = "mock") -> Trajectory:
    """执行并逐帧记录：inputs / outputs / 上下文快照。"""
    t = Trajectory("tr_" + uuid.uuid4().hex[:10], question,
                   prompt_version=prompt_version, model_pin=model_pin)
    ctx: dict[str, Any] = {"question": question, "turn": 0}
    for i, (kind, name, fn) in enumerate(steps, 1):
        out = fn()
        ctx["turn"] = i
        ctx["last_" + kind] = name
        t.frames.append(Frame(i, kind, name, {"question": question, "turn": i},
                              out, context_snapshot=dict(ctx)))
    STORE.save(t)
    return t


def deterministic_replay(trace_id: str, steps: list[tuple[str, str, Callable[[], dict[str, Any]]]],
                         overrides: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """确定性重放：用录制到的 outputs 顶替外部依赖，保证同一 bug 可复现。

    overrides 支持「回到第 N 步改写后重跑」= 时间旅行调试。
    """
    t = STORE.load(trace_id)
    if not t:
        return {"ok": False, "error": "轨迹不存在"}
    overrides = overrides or {}
    frames = []
    for f in t.frames:
        out = overrides.get(f.index, f.outputs)
        frames.append({"index": f.index, "kind": f.kind, "name": f.name,
                       "outputs": out, "overridden": f.index in overrides})
    orig = {f.index: f for f in t.frames}
    replay_t = Trajectory("tr_replay_" + uuid.uuid4().hex[:8], t.question,
                          [Frame(x["index"], x["kind"], x["name"],
                                 orig[x["index"]].inputs, x["outputs"])
                           for x in frames], t.prompt_version, t.model_pin)
    STORE.save(replay_t)
    return {"ok": True, "original": t.trace_id, "replay": replay_t.trace_id,
            "original_digest": t.digest(), "replay_digest": replay_t.digest(),
            "identical": not overrides and t.digest() == replay_t.digest(),
            "time_travel_from": min(overrides) if overrides else None,
            "frames": frames}
