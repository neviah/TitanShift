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


def test_scheduler_job_toggle_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    disable = client.post("/scheduler/jobs/scheduler_heartbeat/enabled", json={"enabled": False})
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False

    tick = client.post("/scheduler/tick")
    assert tick.status_code == 200
    assert "scheduler_heartbeat" not in tick.json()["ran_jobs"]

    missing = client.post("/scheduler/jobs/missing/enabled", json={"enabled": True})
    assert missing.status_code == 404


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


def test_memory_summary_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.get("/memory/summary")
    assert response.status_code == 200
    body = response.json()
    assert "working_entries" in body
    assert "short_term_entries" in body


def test_memory_semantic_search_endpoint() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.memory.embed_and_store(
        doc_id="sem-1",
        text="alpha budget policy",
        metadata={"source": "test"},
        embedding=[0.1, 0.2, 0.3],
    )
    client = TestClient(app)
    response = client.get("/memory/semantic-search?query=alpha&limit=5")
    assert response.status_code == 200
    body = response.json()
    assert any(hit["doc_id"] == "sem-1" for hit in body)


def test_memory_graph_neighbors_endpoint() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.memory.graph_add_node("n1", "concept")
    app.state.runtime.memory.graph_add_node("n2", "concept")
    app.state.runtime.memory.graph_add_edge("n1", "n2", "depends_on")
    client = TestClient(app)
    response = client.get("/memory/graph/neighbors?node_id=n1")
    assert response.status_code == 200
    body = response.json()
    assert body["node_id"] == "n1"
    assert "n2" in body["neighbors"]


def test_api_key_auth_enforced_when_enabled() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("api.require_api_key", True)
    app.state.runtime.config.set("api.api_key", "secret123")
    client = TestClient(app)

    unauthorized = client.get("/status")
    assert unauthorized.status_code == 401

    authorized = client.get("/status", headers={"x-api-key": "secret123"})
    assert authorized.status_code == 200


def test_run_history_report_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    _ = client.post(
        "/chat",
        json={
            "prompt": "history smoke",
            "model_backend": "local_stub",
        },
    )

    response = client.get("/reports/run-history?task_limit=5&log_limit=20")
    assert response.status_code == 200
    body = response.json()
    assert "generated_at" in body
    assert body.get("signing_version") == "v1"
    assert str(body.get("report_hash", "")).startswith("sha256:")
    assert "config_snapshot" in body
    assert "total_tasks" in body
    assert isinstance(body.get("recent_tasks"), list)
    assert isinstance(body.get("recent_events"), list)
    assert isinstance(body.get("health"), list)


def test_run_history_report_hash_changes_with_redaction_mode() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    runtime.logger.log("TEST_HASH", {"token": "sensitive-value", "note": "ok"})
    client = TestClient(app)

    redacted = client.get("/reports/run-history?log_limit=10&redact=true")
    raw = client.get("/reports/run-history?log_limit=10&redact=false")

    assert redacted.status_code == 200
    assert raw.status_code == 200
    assert redacted.json()["report_hash"] != raw.json()["report_hash"]


def test_run_history_report_redacts_sensitive_keys() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    runtime.logger.log("TEST_SECRET", {"api_key": "abc123", "note": "safe"})
    client = TestClient(app)

    response = client.get("/reports/run-history?log_limit=10")
    assert response.status_code == 200
    events = response.json()["recent_events"]
    assert any(e["event_type"] == "TEST_SECRET" for e in events)

    secret_event = next(e for e in events if e["event_type"] == "TEST_SECRET")
    assert secret_event["payload"]["api_key"] == "***REDACTED***"
    assert secret_event["payload"]["note"] == "safe"


def test_run_history_report_policy_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.get("/reports/policy")
    assert response.status_code == 200
    body = response.json()
    assert "redact_by_default" in body
    assert isinstance(body.get("redacted_keys"), list)

