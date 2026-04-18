from __future__ import annotations

import pytest

from harness.api.hooks import ApiHooks
from harness.runtime.bootstrap import build_runtime
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import PermissionPolicy
from harness.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_pre_tool_use_hook_can_abort_execution(tmp_path) -> None:
    hooks = ApiHooks()
    called = {"handler": False}

    async def blocker(payload: dict[str, object]) -> dict[str, object]:
        return {"action": "abort", "error_message": "blocked by test hook"}

    async def handler(args: dict[str, object]) -> dict[str, object]:
        called["handler"] = True
        return {"ok": True}

    hooks.register("PreToolUse", blocker, label="blocker")
    registry = ToolRegistry(
        PermissionPolicy(
            deny_all_by_default=False,
            allow_network=True,
            allowed_paths=[tmp_path],
            allowed_tool_names=set(),
            blocked_tool_names=set(),
            allowed_command_prefixes=["python", "pytest", "git", "npm", "npx", "node"],
        )
    )
    registry.set_hooks(hooks)
    registry.register_tool(
        ToolDefinition(
            name="fake_tool",
            description="fake",
            handler=handler,
            parameters={"type": "object", "properties": {}},
        )
    )

    result = await registry.execute_tool("fake_tool", {}, task_id="task-1")

    assert result["ok"] is False
    assert result["aborted_by_hook"] is True
    assert called["handler"] is False


@pytest.mark.asyncio
async def test_runtime_registers_tenant_tool_filter_hook(tmp_path) -> None:
    runtime = build_runtime(tmp_path)
    called = {"handler": False}

    async def handler(args: dict[str, object]) -> dict[str, object]:
        called["handler"] = True
        return {"ok": True}

    runtime.tools.register_tool(
        ToolDefinition(
            name="tenant_only_tool",
            description="tenant-only",
            handler=handler,
            parameters={"type": "object", "properties": {}},
        )
    )

    result = await runtime.tools.execute_tool(
        "tenant_only_tool",
        {},
        task_id="task-tenant-filter",
        hook_context={"tenant_id": "tenant-a", "allowed_tools": ["some_other_tool"], "call_index": 0},
    )

    assert result["ok"] is False
    assert result["aborted_by_hook"] is True
    assert called["handler"] is False