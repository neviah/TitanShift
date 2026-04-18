"""Async run queue with concurrency cap, per-run timeout, and result tracking.

The ``RunQueue`` enforces ``max_concurrent_runs`` using an asyncio ``Semaphore``.
When all slots are occupied, ``submit()`` returns ``False`` immediately so the
caller can return HTTP 429.  Each run is wrapped with ``asyncio.wait_for`` to
enforce the per-run wall-clock timeout.

Usage (inside an async context)::

    queue = RunQueue(max_workers=4, timeout_s=300)
    ok = await queue.submit(run_id, coro)
    if not ok:
        raise HTTPException(429)
    result = await queue.await_result(run_id)

Concurrency accounting is thread-safe at the asyncio level (single event loop).
Do not share a ``RunQueue`` across multiple event loops.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine


@dataclass
class RunEntry:
    run_id: str
    submitted_at: float
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    result: Any | None = None          # TaskResult-like object
    error: str | None = None
    timed_out: bool = False
    cancelled: bool = False
    state: str = "running"             # running | completed | failed | timeout | cancelled
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None


class RunQueue:
    """Bounded async run queue with per-run timeout enforcement."""

    def __init__(self, max_workers: int = 4, timeout_s: float = 300.0) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._max_workers = max_workers
        self._timeout_s = timeout_s
        self._semaphore = asyncio.Semaphore(max_workers)
        self._runs: dict[str, RunEntry] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @property
    def active_count(self) -> int:
        """Current number of runs that are executing or scheduled."""
        return sum(1 for e in self._runs.values() if e.state == "running")

    @property
    def at_capacity(self) -> bool:
        return self._semaphore._value == 0  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, run_id: str, coro: Coroutine[Any, Any, Any]) -> bool:
        """Try to enqueue *run_id* backed by *coro*.

        Returns ``True`` when the run was accepted (task started), ``False``
        when the queue is at capacity (caller should return 429).
        """
        if self.at_capacity:
            coro.close()
            return False

        entry = RunEntry(run_id=run_id, submitted_at=time.monotonic())
        self._runs[run_id] = entry
        asyncio.create_task(self._execute(entry, coro), name=f"run:{run_id}")
        return True

    async def await_result(self, run_id: str, poll_interval: float = 0.05) -> RunEntry:
        """Wait until *run_id* reaches a terminal state and return its entry."""
        entry = self._runs.get(run_id)
        if entry is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        await entry.completed.wait()
        return entry

    def get_entry(self, run_id: str) -> RunEntry | None:
        return self._runs.get(run_id)

    def get_status(self, run_id: str) -> dict[str, Any] | None:
        entry = self._runs.get(run_id)
        if entry is None:
            return None
        duration_ms: float | None = None
        if entry.finished_at is not None:
            duration_ms = round((entry.finished_at - entry.submitted_at) * 1000, 1)
        return {
            "run_id": run_id,
            "state": entry.state,
            "timed_out": entry.timed_out,
            "cancelled": entry.cancelled,
            "error": entry.error,
            "duration_ms": duration_ms,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        return [self.get_status(rid) for rid in self._runs]  # type: ignore[misc]

    def retry_after_seconds(self) -> int:
        """Suggest a Retry-After value based on average active run duration."""
        running = [e for e in self._runs.values() if e.state == "running"]
        if not running:
            return 5
        # Estimate: half the configured timeout, minimum 5 s
        return max(5, int(self._timeout_s / 2))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute(self, entry: RunEntry, coro: Coroutine[Any, Any, Any]) -> None:
        async with self._semaphore:
            try:
                result = await asyncio.wait_for(coro, timeout=self._timeout_s)
                entry.result = result
                entry.state = "completed"
            except asyncio.TimeoutError:
                entry.timed_out = True
                entry.state = "timeout"
                entry.error = f"Run exceeded timeout of {self._timeout_s}s"
            except asyncio.CancelledError:
                entry.cancelled = True
                entry.state = "cancelled"
                entry.error = "Run was cancelled"
                raise
            except Exception as exc:  # noqa: BLE001
                entry.state = "failed"
                entry.error = str(exc)
            finally:
                entry.finished_at = time.monotonic()
                entry.completed.set()
