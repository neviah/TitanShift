from __future__ import annotations

import asyncio

import pytest

from harness.api.hooks import ApiHooks
from harness.api.hooks import HookPayload


@pytest.mark.asyncio
async def test_hook_registry_runs_in_priority_order() -> None:
    hooks = ApiHooks()
    seen: list[str] = []

    async def later(payload: dict[str, object]) -> None:
        seen.append("later")

    async def earlier(payload: dict[str, object]) -> None:
        seen.append("earlier")

    hooks.register("PreToolUse", later, priority=50, label="later")
    hooks.register("PreToolUse", earlier, priority=10, label="earlier")

    await hooks.emit(HookPayload(event="PreToolUse", data={}))

    assert seen == ["earlier", "later"]


@pytest.mark.asyncio
async def test_hook_registry_unregisters_by_label() -> None:
    hooks = ApiHooks()
    seen: list[str] = []

    async def callback(payload: dict[str, object]) -> None:
        seen.append("called")

    label = hooks.register("Stop", callback, label="stopper")
    assert label == "stopper"
    assert hooks.unregister(label="stopper") is True

    await hooks.emit(HookPayload(event="Stop", data={}))

    assert seen == []


@pytest.mark.asyncio
async def test_hook_registry_times_out_and_returns_error_directive() -> None:
    hooks = ApiHooks()

    async def slow(payload: dict[str, object]) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"action": "allow"}

    hooks.register("PreToolUse", slow, timeout_s=0.001, label="slow")

    results = await hooks.execute("PreToolUse", {"tool_name": "read_file"})

    assert len(results) == 1
    assert results[0]["action"] == "error"
    assert results[0]["label"] == "slow"


@pytest.mark.asyncio
async def test_hook_registry_execute_collects_directives() -> None:
    hooks = ApiHooks()

    async def allow(payload: dict[str, object]) -> dict[str, object]:
        return {"action": "allow"}

    async def replace(payload: dict[str, object]) -> dict[str, object]:
        return {"action": "replace_args", "modified_args": {"path": "README.md"}}

    hooks.register("PreToolUse", allow, priority=10, label="allow")
    hooks.register("PreToolUse", replace, priority=20, label="replace")

    results = await hooks.execute("PreToolUse", {"tool_name": "read_file"})

    assert [row["action"] for row in results] == ["allow", "replace_args"]