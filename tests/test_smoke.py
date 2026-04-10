from pathlib import Path
import asyncio
from fastapi.testclient import TestClient

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


def test_chat_budget_override_returns_error_state() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "prompt": "This should exceed tiny budget",
            "model_backend": "local_stub",
            "budget": {"max_tokens": 1},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"] is not None


def test_status_includes_health() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("health"), list)
    assert any(item.get("name") == "orchestrator" for item in body.get("health", []))


def test_orchestrator_failure_isolation_marks_task_failed() -> None:
    runtime = build_runtime(Path(".").resolve())

    class BrokenStateMachine:
        async def run_task(self, task: Task):
            raise RuntimeError("boom")

    runtime.orchestrator.state_machine = BrokenStateMachine()  # type: ignore[assignment]
    result = asyncio.run(runtime.orchestrator.run_reactive_task(Task(id="fail-1", description="should fail")))
    assert result.success is False
    assert "Unhandled runtime error" in (result.error or "")


def test_logs_endpoint_returns_list() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    _ = client.post(
        "/chat",
        json={
            "prompt": "log smoke",
            "model_backend": "local_stub",
        },
    )
    response = client.get("/logs?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all("event_type" in row for row in body)


def test_config_update_endpoint_runtime_override() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    before = client.get("/config").json()
    assert "state_machine.default_budget.max_tokens" in before

    response = client.post(
        "/config",
        json={"key": "state_machine.default_budget.max_tokens", "value": 2048},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["key"] == "state_machine.default_budget.max_tokens"
    assert body["value"] == 2048


def test_scheduler_endpoints() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    jobs = client.get("/scheduler/jobs")
    assert jobs.status_code == 200
    jobs_body = jobs.json()
    assert isinstance(jobs_body, list)
    assert any(j.get("job_id") == "scheduler_heartbeat" for j in jobs_body)

    hb = client.post("/scheduler/heartbeat")
    assert hb.status_code == 200
    hb_body = hb.json()
    assert hb_body["heartbeat_count"] >= 1

    tick = client.post("/scheduler/tick")
    assert tick.status_code == 200
    tick_body = tick.json()
    assert "ran_jobs" in tick_body


def test_agents_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.get("/agents")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["agent_id"] == "main-agent"


def test_skills_endpoint_and_search() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.get("/skills")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert any(row["skill_id"] == "reactive_chat" for row in body)

    response_q = client.get("/skills?query=shell")
    assert response_q.status_code == 200
    body_q = response_q.json()
    assert any(row["skill_id"] == "safe_shell_command" for row in body_q)


def test_tools_endpoint_and_search() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.get("/tools")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert any(row["name"] == "shell_command" for row in body)

    response_q = client.get("/tools?query=shell")
    assert response_q.status_code == 200
    body_q = response_q.json()
    assert any(row["name"] == "shell_command" for row in body_q)

