from pathlib import Path
import asyncio

from harness.api.server import create_app
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.runtime.bootstrap import build_runtime
from harness.model.adapter import ModelRegistry
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import PermissionPolicy


def test_defaults_load() -> None:
    cfg = ConfigManager(Path("."))
    assert cfg.get("memory.graph_backend") == "networkx"
    assert cfg.get("tools.deny_all_by_default") is True


def test_api_factory() -> None:
    app = create_app(Path(".").resolve())
    assert app.title == "TitantShift Harness API"


def test_model_backends_registered() -> None:
    cfg = ConfigManager(Path("."))
    registry = ModelRegistry.from_config(cfg)
    assert "local_stub" in registry.adapters
    assert "lmstudio" in registry.adapters


def test_budget_enforcement_reactive() -> None:
    runtime = build_runtime(Path(".").resolve())
    task = Task(
        id="budget-test",
        description="This prompt should exceed tiny token budget",
        input={"model_backend": "local_stub", "budget": {"max_tokens": 1}},
    )
    result = asyncio.run(runtime.orchestrator.run_reactive_task(task))
    assert result.success is False
    assert result.error is not None


def test_permission_policy_deny_all() -> None:
    policy = PermissionPolicy(
        deny_all_by_default=True,
        allow_network=False,
        allowed_paths=[],
        allowed_tool_names=set(),
        blocked_tool_names=set(),
        allowed_command_prefixes=[],
    )
    allowed, reason = policy.evaluate_tool(ToolDefinition(name="demo", description="demo"), args={})
    assert allowed is False
    assert reason == "tool_not_in_allowlist"


def test_execution_policy_blocks_unknown_command() -> None:
    policy = ExecutionPolicy(
        allowed_cwd_roots=[Path(".").resolve()],
        allowed_command_prefixes=["git", "echo"],
        max_runtime_s=10,
        max_output_bytes=1024,
    )
    runner = ExecutionModule(policy=policy, default_cwd=Path("."))
    try:
        asyncio.run(runner.run_command("whoami"))
        assert False, "Expected ExecutionDeniedError"
    except ExecutionDeniedError:
        assert True


def test_builtin_shell_command_tool_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("shell_command")
    assert tool is not None
