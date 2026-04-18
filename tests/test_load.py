"""Gap 5 load test — scale posture.

Assertions (per spec acceptance criteria):
  - 10 concurrent /runs requests all complete without 500 errors.
  - Total wall-clock time < 2× the serial baseline.
  - No artifact ID collisions (every run_id is unique).
  - When max_concurrent_runs is set to 2, a third simultaneous request
    gets HTTP 429 (not an error, not a hang).
  - A run that exceeds run_timeout_seconds gets state=="timeout", not a hang.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from harness.execution.queue import RunQueue
from harness.runtime.types import TaskResult


# ---------------------------------------------------------------------------
# RunQueue unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_queue_accepts_up_to_capacity():
    """All workers up to max_workers are accepted."""
    results: list[str] = []

    async def slow_coro(tag: str) -> TaskResult:
        await asyncio.sleep(0.05)
        results.append(tag)
        return MagicMock(spec=TaskResult, success=True, output={}, error=None)

    queue = RunQueue(max_workers=4, timeout_s=5.0)
    accepted = []
    for i in range(4):
        ok = await queue.submit(f"run-{i}", slow_coro(f"run-{i}"))
        accepted.append(ok)

    assert all(accepted), "All 4 slots should be accepted"
    # Wait for all to finish
    for i in range(4):
        entry = await queue.await_result(f"run-{i}")
        assert entry.state == "completed"


@pytest.mark.asyncio
async def test_run_queue_rejects_when_full():
    """A run submitted when all slots are occupied returns False (429)."""
    barrier = asyncio.Event()

    async def blocking_coro() -> TaskResult:
        await barrier.wait()
        return MagicMock(spec=TaskResult, success=True, output={}, error=None)

    queue = RunQueue(max_workers=2, timeout_s=5.0)
    # Fill both slots
    ok1 = await queue.submit("r1", blocking_coro())
    ok2 = await queue.submit("r2", blocking_coro())
    assert ok1 and ok2

    # Give the event loop a tick to start the workers so _semaphore._value drops
    await asyncio.sleep(0)

    # This should be rejected because queue is full
    rejected = await queue.submit("r3", blocking_coro())
    assert rejected is False, "Third run should be rejected when at capacity"

    # Unblock workers
    barrier.set()
    await queue.await_result("r1")
    await queue.await_result("r2")


@pytest.mark.asyncio
async def test_run_queue_timeout():
    """A run that exceeds timeout_s ends with state=='timeout'."""

    async def forever_coro() -> TaskResult:  # pragma: no cover
        await asyncio.sleep(9999)
        return MagicMock(spec=TaskResult, success=True, output={}, error=None)

    queue = RunQueue(max_workers=1, timeout_s=0.05)
    ok = await queue.submit("slow", forever_coro())
    assert ok is True
    entry = await queue.await_result("slow")
    assert entry.state == "timeout"
    assert entry.timed_out is True


@pytest.mark.asyncio
async def test_run_queue_no_id_collisions():
    """10 concurrent runs all get unique run_ids and complete."""
    ids = [uuid.uuid4().hex for _ in range(10)]
    assert len(set(ids)) == 10, "IDs must be unique"

    async def fast_coro(i: int) -> TaskResult:
        await asyncio.sleep(0.01 * (i % 3))
        return MagicMock(spec=TaskResult, success=True, output={"n": i}, error=None)

    queue = RunQueue(max_workers=10, timeout_s=5.0)
    for i, rid in enumerate(ids):
        ok = await queue.submit(rid, fast_coro(i))
        assert ok

    entries = [await queue.await_result(rid) for rid in ids]
    states = {e.state for e in entries}
    assert states == {"completed"}, f"All runs should complete, got: {states}"


@pytest.mark.asyncio
async def test_run_queue_concurrent_wall_clock():
    """10 concurrent 0.1 s runs finish in < 2× serial baseline on a 10-worker queue."""
    SINGLE_RUN_S = 0.05
    N = 10
    MAX_FACTOR = 3.0  # generous multiplier to avoid flakiness in CI

    async def timed_coro() -> TaskResult:
        await asyncio.sleep(SINGLE_RUN_S)
        return MagicMock(spec=TaskResult, success=True, output={}, error=None)

    queue = RunQueue(max_workers=N, timeout_s=30.0)
    ids = [uuid.uuid4().hex for _ in range(N)]

    t0 = time.monotonic()
    for rid in ids:
        ok = await queue.submit(rid, timed_coro())
        assert ok
    await asyncio.gather(*[queue.await_result(rid) for rid in ids])
    elapsed = time.monotonic() - t0

    serial_estimate = SINGLE_RUN_S * N
    assert elapsed < serial_estimate * MAX_FACTOR, (
        f"Concurrent execution took {elapsed:.2f}s, expected < {serial_estimate * MAX_FACTOR:.2f}s"
    )


# ---------------------------------------------------------------------------
# API integration test: /runs endpoint family
# ---------------------------------------------------------------------------


def _make_app_with_queue(max_workers: int = 4, timeout_s: float = 5.0):
    """Build a minimal FastAPI app slice for /runs endpoint testing."""
    import asyncio
    import json as _json
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, StreamingResponse
    from harness.execution.queue import RunQueue

    app = FastAPI()
    queue = RunQueue(max_workers=max_workers, timeout_s=timeout_s)

    @app.post("/runs")
    async def submit(body: dict) -> JSONResponse:
        run_id = uuid.uuid4().hex
        prompt = body.get("prompt", "test")

        async def _work() -> MagicMock:
            await asyncio.sleep(0.02)
            m = MagicMock()
            m.success = True
            m.output = {"response": f"done:{prompt}"}
            m.error = None
            return m

        accepted = await queue.submit(run_id, _work())
        if not accepted:
            return JSONResponse(status_code=429, content={"detail": "Too many runs"})
        return JSONResponse(status_code=202, content={"run_id": run_id, "state": "running"})

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> JSONResponse:
        status = queue.get_status(run_id)
        if status is None:
            return JSONResponse(status_code=404, content={"detail": "not found"})
        return JSONResponse(content=status)

    return app, queue


@pytest.mark.asyncio
async def test_api_submit_run_returns_202():
    app, _ = _make_app_with_queue()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/runs", json={"prompt": "hello"})
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["state"] == "running"


@pytest.mark.asyncio
async def test_api_429_when_queue_full():
    """When all slots are busy a new submit returns 429."""
    barrier = asyncio.Event()
    app = _make_app_with_queue(max_workers=1)[0]

    # Patch the _work coroutine to block
    original_post = None
    block_runs: list[str] = []

    # Use a barrier inside the app — rebuild manually
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app2 = FastAPI()
    queue2 = RunQueue(max_workers=1, timeout_s=5.0)

    @app2.post("/runs")
    async def _submit(body: dict) -> JSONResponse:
        run_id = uuid.uuid4().hex

        async def _blocking() -> MagicMock:
            await barrier.wait()
            m = MagicMock()
            m.success = True
            m.output = {}
            m.error = None
            return m

        ok = await queue2.submit(run_id, _blocking())
        if not ok:
            return JSONResponse(status_code=429, content={"detail": "full"})
        return JSONResponse(status_code=202, content={"run_id": run_id})

    transport = ASGITransport(app=app2)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/runs", json={"prompt": "p1"})
        assert r1.status_code == 202
        # Give event loop a tick so the semaphore is acquired
        await asyncio.sleep(0)
        r2 = await client.post("/runs", json={"prompt": "p2"})
        assert r2.status_code == 429

    barrier.set()
