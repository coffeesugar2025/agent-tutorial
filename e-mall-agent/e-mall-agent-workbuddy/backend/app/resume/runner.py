"""Resume a long-running async step sequence from its last checkpoint."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from .checkpoint import CheckpointStore, InMemoryCheckpointStore, TaskCheckpoint

StepFn = Callable[..., Any]


class ResumeLimitExceeded(RuntimeError):
    """Raised when a task has been resumed more than ``max_resumes`` times."""


@dataclass
class StepContext:
    task_id: str
    step_index: int
    resume_count: int


@dataclass
class Step:
    name: str
    fn: StepFn
    idempotent: bool = True


def _normalise_step(raw: Any) -> Step:
    if isinstance(raw, Step):
        return raw
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], str):
        return Step(name=raw[0], fn=raw[1])
    if callable(raw):
        return Step(name=getattr(raw, "__name__", type(raw).__name__), fn=raw)
    raise TypeError(f"无法识别的步骤: {raw!r}")


class ResumableRunner:
    """Execute steps, checkpointing after each one.

    ``run`` starts from step 0; ``resume`` loads the latest checkpoint for a
    task and continues at the following step.  Idempotent steps that were
    already completed are skipped, even when resuming from an earlier index.
    """

    def __init__(self, steps: Iterable[Any], store: CheckpointStore | None = None,
                 max_resumes: int = 3) -> None:
        self.steps: list[Step] = [_normalise_step(s) for s in steps]
        self.store = store or InMemoryCheckpointStore()
        self.max_resumes = max_resumes
        self._resume_counts: dict[str, int] = {}
        self._completed: set[tuple[str, int]] = set()

    async def _invoke(self, step: Step, state: dict, ctx: StepContext) -> Any:
        try:
            params = list(inspect.signature(step.fn).parameters.values())
            required = [p for p in params
                        if p.default is inspect.Parameter.empty
                        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            argc = len(required)
        except (TypeError, ValueError):
            argc = 2
        args: tuple[Any, ...]
        if argc <= 1:
            args = (state,)
        else:
            args = (state, ctx)
        result = step.fn(*args)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _execute(self, task_id: str, start: int, state: dict,
                       stop_after: int | None) -> dict[str, Any]:
        executed = 0
        for index in range(max(0, start), len(self.steps)):
            step = self.steps[index]
            key = (task_id, index)
            if step.idempotent and key in self._completed:
                continue
            executed += 1
            ctx = StepContext(
                task_id=task_id, step_index=index,
                resume_count=self._resume_counts.get(task_id, 0),
            )
            output = await self._invoke(step, state, ctx)
            if output is not None:
                state = dict(output) if isinstance(output, dict) else dict(state)
            self.store.save(TaskCheckpoint(
                task_id=task_id, step_index=index, state=dict(state),
            ))
            self._completed.add(key)
            if stop_after is not None and index >= stop_after:
                return {
                    "task_id": task_id, "state": dict(state),
                    "step_index": index, "steps_run": executed,
                    "interrupted": True, "completed": False,
                }
        return {
            "task_id": task_id, "state": dict(state),
            "step_index": len(self.steps) - 1,
            "steps_run": executed,
            "interrupted": False, "completed": True,
        }

    async def run(self, task_id: str, initial_state: dict | None = None,
                  stop_after: int | None = None) -> dict[str, Any]:
        """Run all steps from the beginning; ``stop_after`` simulates a crash."""
        return await self._execute(task_id, 0, dict(initial_state or {}), stop_after)

    async def resume(self, task_id: str, stop_after: int | None = None,
                     from_step: int | None = None) -> dict[str, Any]:
        """Continue a task from its latest checkpoint (or ``from_step``)."""
        checkpoint = self.store.load(task_id)
        if checkpoint is None:
            raise KeyError(f"任务不存在或没有检查点: {task_id}")
        used = self._resume_counts.get(task_id, 0)
        if used >= self.max_resumes:
            raise ResumeLimitExceeded(
                f"任务 {task_id} 恢复次数超过上限 {self.max_resumes}"
            )
        self._resume_counts[task_id] = used + 1
        start = from_step if from_step is not None else checkpoint.step_index + 1
        return await self._execute(task_id, start, dict(checkpoint.state), stop_after)

    @property
    def resume_counts(self) -> dict[str, int]:
        return dict(self._resume_counts)


__all__ = [
    "ResumableRunner", "Step", "StepContext", "ResumeLimitExceeded",
]
