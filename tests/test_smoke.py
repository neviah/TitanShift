from pathlib import Path
import asyncio
import hashlib
import json
import os
import time

from nacl.encoding import Base64Encoder
from nacl.signing import SigningKey
from fastapi.testclient import TestClient as FastAPITestClient

from harness.api.client import HarnessApiClient
from harness.api.server import create_app
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.runtime.bootstrap import build_runtime
from harness.model.adapter import CloudOpenAIAdapter, LMStudioAdapter, ModelRegistry
from harness.runtime.config import ConfigManager
from harness.scheduler.module import ScheduledJob, Scheduler
from harness.runtime.types import Task
from harness.skills.registry import SkillDefinition
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import PermissionPolicy


class TestClient(FastAPITestClient):
    def __init__(self, app, *args, normalize_runtime: bool = True, **kwargs):
        super().__init__(app, *args, **kwargs)
        if not normalize_runtime:
            return

        runtime = getattr(self.app.state, "runtime", None)
        if runtime is None:
            return

        # Keep smoke tests independent of committed local-only settings.
        if float(runtime.config.get("orchestrator.skill_execution_timeout_s", 15.0)) == 0.01:
            runtime.config.set("orchestrator.skill_execution_timeout_s", 15.0)
        if int(runtime.config.get("reports.max_export_bytes", 262144)) == 64:
            runtime.config.set("reports.max_export_bytes", 262144)

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        runtime = getattr(self.app.state, "runtime", None)
        headers = dict(kwargs.pop("headers", {}) or {})
        normalized_header_keys = {str(k).lower(): v for k, v in headers.items()}
        used_injected_key = ""

        if runtime is not None and "x-api-key" not in normalized_header_keys:
            require_read = bool(runtime.config.get("api.require_api_key", False))
            read_key = str(runtime.config.get("api.api_key", "")).strip()
            if require_read and read_key:
                headers["x-api-key"] = read_key
                used_injected_key = read_key

        kwargs["headers"] = headers
        response = super().request(method, url, *args, **kwargs)

        if runtime is None:
            return response

        method_upper = str(method).upper()
        require_admin = bool(runtime.config.get("api.require_admin_api_key", False))
        admin_key = str(runtime.config.get("api.admin_api_key", "")).strip()
        explicit_key_present = "x-api-key" in normalized_header_keys
        is_mutating = method_upper in {"POST", "PUT", "PATCH", "DELETE"}

        if (
            response.status_code == 401
            and not explicit_key_present
            and is_mutating
            and require_admin
            and admin_key
            and admin_key != used_injected_key
        ):
            retry_headers = dict(headers)
            retry_headers["x-api-key"] = admin_key
            kwargs["headers"] = retry_headers
            return super().request(method, url, *args, **kwargs)

        return response


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
    client = TestClient(app, normalize_runtime=False)
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
    client = TestClient(app, normalize_runtime=False)
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
    client = TestClient(app, normalize_runtime=False)
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
    assert isinstance(body, dict)
    assert isinstance(body.get("items"), list)
    assert all("event_type" in row for row in body["items"])
    assert "has_more" in body


def test_logs_endpoint_supports_offset_and_time_filters() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    for idx in range(3):
        runtime.logger.log("TEST_PAGED_LOG", {"source": "paged-test", "idx": idx})
    client = TestClient(app, normalize_runtime=False)

    baseline = client.get("/logs?event_type=TEST_PAGED_LOG&source=paged-test&limit=3")
    assert baseline.status_code == 200
    rows = baseline.json()["items"]
    assert len(rows) == 3

    paged = client.get("/logs?event_type=TEST_PAGED_LOG&source=paged-test&limit=2&offset=1")
    assert paged.status_code == 200
    paged_body = paged.json()
    paged_rows = paged_body["items"]
    assert len(paged_rows) == 2
    assert paged_rows[-1]["payload"]["idx"] == rows[-2]["payload"]["idx"]
    assert paged_body["has_more"] in [True, False]

    after = rows[1]["timestamp"]
    filtered = client.get(
        "/logs",
        params={"event_type": "TEST_PAGED_LOG", "source": "paged-test", "after": after, "limit": 5},
    )
    assert filtered.status_code == 200
    filtered_rows = filtered.json()["items"]
    assert all(r["timestamp"] >= after for r in filtered_rows)


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


def test_scheduler_auto_disables_repeated_failures() -> None:
    scheduler = Scheduler()

    def broken_job() -> None:
        raise RuntimeError("expected failure")

    scheduler.register_job(
        ScheduledJob(
            job_id="broken-job",
            description="fails for guardrail test",
            callback=broken_job,
            max_failures=2,
        )
    )

    first = asyncio.run(scheduler.tick())
    assert "broken-job" in first["failed_jobs"]
    assert "broken-job" not in first["auto_disabled_jobs"]

    second = asyncio.run(scheduler.tick())
    assert "broken-job" in second["failed_jobs"]
    assert "broken-job" in second["auto_disabled_jobs"]

    job = scheduler.get_job("broken-job")
    assert job is not None
    assert job.enabled is False
    assert job.failure_count == 2
    assert job.last_error == "expected failure"


def test_scheduler_timeout_counts_as_failure_and_auto_disables() -> None:
    scheduler = Scheduler()

    async def slow_job() -> None:
        await asyncio.sleep(0.05)

    scheduler.register_job(
        ScheduledJob(
            job_id="slow-job",
            description="times out for guardrail test",
            callback=slow_job,
            timeout_s=0.01,
            max_failures=1,
        )
    )

    result = asyncio.run(scheduler.tick())
    assert "slow-job" in result["failed_jobs"]
    assert "slow-job" in result["timed_out_jobs"]
    assert "slow-job" in result["auto_disabled_jobs"]

    job = scheduler.get_job("slow-job")
    assert job is not None
    assert job.enabled is False
    assert job.failure_count == 1
    assert job.last_error == "Timed out after 0.01s"


def test_scheduler_interval_job_runs_once_without_elapsed_interval() -> None:
    scheduler = Scheduler()
    run_count = {"value": 0}

    def interval_job() -> None:
        run_count["value"] += 1

    scheduler.register_job(
        ScheduledJob(
            job_id="interval-job",
            description="interval due behavior",
            schedule_type="interval",
            interval_seconds=60,
            callback=interval_job,
        )
    )

    first = asyncio.run(scheduler.tick())
    second = asyncio.run(scheduler.tick())
    assert "interval-job" in first["ran_jobs"]
    assert "interval-job" not in second["ran_jobs"]
    assert run_count["value"] == 1


def test_scheduler_cron_job_runs_once_per_minute_window() -> None:
    scheduler = Scheduler()
    run_count = {"value": 0}

    def cron_job() -> None:
        run_count["value"] += 1

    scheduler.register_job(
        ScheduledJob(
            job_id="cron-job",
            description="cron due behavior",
            schedule_type="cron",
            cron="* * * * *",
            callback=cron_job,
        )
    )

    first = asyncio.run(scheduler.tick())
    second = asyncio.run(scheduler.tick())
    assert "cron-job" in first["ran_jobs"]
    assert "cron-job" not in second["ran_jobs"]
    assert run_count["value"] == 1


def test_scheduler_tick_escalates_missed_heartbeat_to_emergency() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    runtime.scheduler.set_heartbeat_timeout(1.0)
    runtime.scheduler.last_heartbeat_at = "2000-01-01T00:00:00+00:00"
    client = TestClient(app)

    tick = client.post("/scheduler/tick")
    assert tick.status_code == 200
    body = tick.json()
    assert body["missed_heartbeat"] is True
    assert body["newly_missed_heartbeat"] is True

    diag_logs = client.get("/logs?event_type=EMERGENCY_DIAGNOSIS&source=scheduler.heartbeat&limit=5")
    assert diag_logs.status_code == 200
    rows = diag_logs.json()["items"]
    assert rows
    assert rows[-1]["payload"]["source"] == "scheduler.heartbeat"


def test_scheduler_register_maintenance_jobs_endpoint_is_idempotent() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    first = client.post("/scheduler/maintenance/register")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["ok"] is True
    assert "maintenance_health_snapshot" in first_body["registered_jobs"]
    assert "maintenance_retention_preview" in first_body["registered_jobs"]

    second = client.post("/scheduler/maintenance/register")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["registered_jobs"] == []


def test_scheduler_maintenance_jobs_emit_telemetry_on_tick() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    registered = client.post("/scheduler/maintenance/register")
    assert registered.status_code == 200

    tick = client.post("/scheduler/tick")
    assert tick.status_code == 200
    body = tick.json()
    assert "maintenance_health_snapshot" in body["ran_jobs"]
    assert "maintenance_retention_preview" in body["ran_jobs"]

    logs = client.get("/logs?event_type=MAINTENANCE_HEALTH_SNAPSHOT&limit=5")
    assert logs.status_code == 200
    assert logs.json()["items"]


def test_scheduler_endpoint_returns_failure_guardrail_fields() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    jobs = client.get("/scheduler/jobs")
    assert jobs.status_code == 200
    row = next(j for j in jobs.json() if j["job_id"] == "scheduler_heartbeat")
    assert "timeout_s" in row
    assert "max_failures" in row
    assert "failure_count" in row
    assert "last_error" in row


def test_agents_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    response = client.get("/agents")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["agent_id"] == "main-agent"


def test_agents_spawn_endpoint_when_enabled() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawn = client.post(
        "/agents/spawn",
        json={"description": "Run shell command safely", "role": "Execution Specialist"},
    )
    assert spawn.status_code == 200
    body = spawn.json()
    assert body["ok"] is True
    assert body["agent_id"].startswith("subagent-")
    assert isinstance(body["assigned_skills"], list)

    agents = client.get("/agents")
    assert agents.status_code == 200
    rows = agents.json()
    assert any(row["agent_id"] == body["agent_id"] for row in rows)


def test_agents_assign_skills_endpoint() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200
    body = assigned.json()
    assert body["ok"] is True
    assert body["agent_id"] == agent_id
    assert "safe_shell_command" in body["assigned_skills"]
    assert "shell_command" in body["allowed_tools"]


def test_agent_scoped_skill_execute_endpoint_and_audit_log() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    forbidden = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert forbidden.status_code == 403

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200

    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["ok"] is True
    assert body["execution_id"].startswith("exec-")
    assert body["agent_id"] == agent_id
    assert body["skill_id"] == "safe_shell_command"

    logs = client.get("/logs?event_type=AGENT_SKILL_EXECUTED&limit=5")
    assert logs.status_code == 200
    log_rows = logs.json()["items"]
    assert any(r["payload"].get("execution_id") == body["execution_id"] for r in log_rows)


def test_agent_scoped_skill_execute_timeout_emits_emergency_diagnosis() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    app.state.runtime.config.set("orchestrator.skill_execution_timeout_s", 0.01)
    runtime = app.state.runtime

    runtime.skills.register_skill(
        SkillDefinition(
            skill_id="slow_skill",
            description="Slow skill for timeout test",
            mode="code",
            tags=["test", "slow"],
            required_tools=[],
        )
    )

    async def _slow_handler(_: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"ok": True}

    runtime.skills.register_code_handler("slow_skill", _slow_handler)
    client = TestClient(app, normalize_runtime=False)

    spawned = client.post("/agents/spawn", json={"description": "Need slow skill"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["slow_skill"]})
    assert assigned.status_code == 200

    timed_out = client.post(
        f"/agents/{agent_id}/skills/slow_skill/execute",
        json={"input": {}},
    )
    assert timed_out.status_code == 504

    diag_logs = client.get("/logs?event_type=EMERGENCY_DIAGNOSIS&limit=10")
    assert diag_logs.status_code == 200
    rows = diag_logs.json()["items"]
    matching = [r for r in rows if r["payload"].get("source") == "orchestrator.skill_execution"]
    assert matching
    diagnoses = matching[-1]["payload"].get("diagnoses", [])
    assert any("configured execution budget" in d.get("hypothesis", "") for d in diagnoses)
    assert any("orchestrator.skill_execution_timeout_s" in d.get("suggested_fix", "") for d in diagnoses)


def test_emergency_diagnosis_for_policy_blocked_skill_execution() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    runtime = app.state.runtime
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200

    runtime.tools.policy.allowed_tool_names.clear()
    blocked = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert blocked.status_code == 403

    diag_logs = client.get("/logs?event_type=EMERGENCY_DIAGNOSIS&limit=10")
    assert diag_logs.status_code == 200
    rows = diag_logs.json()["items"]
    matching = [r for r in rows if r["payload"].get("source") == "orchestrator.skill_execution"]
    assert matching
    diagnoses = matching[-1]["payload"].get("diagnoses", [])
    assert any("Execution policy blocked" in d.get("hypothesis", "") for d in diagnoses)
    assert any("allowed_command_prefixes" in d.get("suggested_fix", "") for d in diagnoses)


def test_skills_endpoint_and_search() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.get("/skills")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert any(row["skill_id"] == "reactive_chat" for row in body)
    assert all("mode" in row for row in body)

    response_q = client.get("/skills?query=shell")
    assert response_q.status_code == 200
    body_q = response_q.json()
    assert any(row["skill_id"] == "safe_shell_command" for row in body_q)

    response_tag = client.get("/skills?tags=safety")
    assert response_tag.status_code == 200
    body_tag = response_tag.json()
    assert any(row["skill_id"] == "safe_shell_command" for row in body_tag)

    response_related = client.get("/skills?related_node_id=tool:shell_command")
    assert response_related.status_code == 200
    body_related = response_related.json()
    assert any(row["skill_id"] == "safe_shell_command" for row in body_related)
    assert body_related[0]["skill_id"] == "safe_shell_command"
    assert body_related[0]["ranking_score"] is not None


def test_skills_market_list_endpoint(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "skill_id": "market_alpha",
                    "description": "Market skill alpha",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.1.0",
                    "tags": ["alpha"],
                    "required_tools": [],
                    "dependencies": [],
                    "prompt_template": "alpha {input}",
                }
            ]
        ),
        encoding="utf-8",
    )
    installed_path.write_text(json.dumps(["market_alpha"]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.get("/skills/market")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["skill_id"] == "market_alpha"
    assert body[0]["name"] == "Market Alpha"
    assert body[0]["installed"] is True


def test_skills_market_install_enforces_dependencies(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "skill_id": "dep_skill",
                    "description": "Dependency skill",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.1.0",
                    "tags": [],
                    "required_tools": [],
                    "dependencies": [],
                    "prompt_template": "dep {input}",
                },
                {
                    "skill_id": "root_skill",
                    "description": "Root skill",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.1.0",
                    "tags": [],
                    "required_tools": [],
                    "dependencies": ["dep_skill"],
                    "prompt_template": "root {input}",
                },
            ]
        ),
        encoding="utf-8",
    )
    installed_path.write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)

    blocked = client.post("/skills/market/install", json={"skill_id": "root_skill"})
    assert blocked.status_code == 400

    dep = client.post("/skills/market/install", json={"skill_id": "dep_skill"})
    assert dep.status_code == 200

    root = client.post("/skills/market/install", json={"skill_id": "root_skill"})
    assert root.status_code == 200
    assert root.json()["installed"] is True


def test_skills_market_uninstall_blocks_when_dependents_present(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "skill_id": "dep_skill",
                    "description": "Dependency skill",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.1.0",
                    "tags": [],
                    "required_tools": [],
                    "dependencies": [],
                    "prompt_template": "dep {input}",
                },
                {
                    "skill_id": "root_skill",
                    "description": "Root skill",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.1.0",
                    "tags": [],
                    "required_tools": [],
                    "dependencies": ["dep_skill"],
                    "prompt_template": "root {input}",
                },
            ]
        ),
        encoding="utf-8",
    )
    installed_path.write_text(json.dumps(["dep_skill", "root_skill"]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)
    blocked = client.post("/skills/market/uninstall", json={"skill_id": "dep_skill"})
    assert blocked.status_code == 400


def test_skills_market_rejects_invalid_skill_id(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(json.dumps([]), encoding="utf-8")
    installed_path.write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post("/skills/market/install", json={"skill_id": "../bad"})
    assert response.status_code == 400


def test_skills_market_update_endpoint(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "skill_id": "market_alpha",
                    "description": "Market skill alpha",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "0.2.0",
                    "tags": ["alpha"],
                    "required_tools": [],
                    "dependencies": [],
                    "prompt_template": "alpha {input}",
                }
            ]
        ),
        encoding="utf-8",
    )
    installed_path.write_text(json.dumps(["market_alpha"]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post("/skills/market/update", json={"skill_id": "market_alpha"})
    assert response.status_code == 200
    body = response.json()
    assert body["updated"] is True
    assert body["version"] == "0.2.0"


def test_skills_market_remote_sync_and_status(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(json.dumps([]), encoding="utf-8")
    installed_path.write_text(json.dumps([]), encoding="utf-8")

    remote_items = [
        {
            "skill_id": "remote_alpha",
            "description": "Remote alpha skill",
            "mode": "prompt",
            "domain": "remote",
            "version": "1.0.0",
            "tags": ["remote"],
            "required_tools": [],
            "dependencies": [],
            "prompt_template": "remote {input}",
        }
    ]
    signing_key = SigningKey.generate()
    verify_key_b64 = signing_key.verify_key.encode(encoder=Base64Encoder).decode("utf-8")
    signature_payload = {
        "source": "test-remote",
        "generated_at": "2026-04-10T00:00:00+00:00",
        "signing_version": "v2-ed25519",
        "items": remote_items,
    }
    signature = signing_key.sign(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).signature
    signature_b64 = Base64Encoder.encode(signature).decode("utf-8")
    digest = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    remote_index = {
        **signature_payload,
        "public_key": verify_key_b64,
        "signature": signature_b64,
        "index_hash": f"sha256:{digest}",
    }
    remote_index_path = tmp_path / "remote-index.json"
    remote_index_path.write_text(json.dumps(remote_index), encoding="utf-8")

    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                    "market_remote_cache_file": "remote_cache.json",
                    "market_remote_status_file": "remote_status.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)

    sync = client.post("/skills/market/remote/sync", json={"source": str(remote_index_path)})
    assert sync.status_code == 200
    sync_body = sync.json()
    assert sync_body["ok"] is True
    assert sync_body["pulled_count"] == 1

    market = client.get("/skills/market")
    assert market.status_code == 200
    assert any(item["skill_id"] == "remote_alpha" for item in market.json())

    status = client.get("/skills/market/remote/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["synced"] is True
    assert status_body["pulled_count"] == 1
    assert status_body["index_hash"] == sync_body["index_hash"]
    assert sync_body["index_hash"].startswith("sha256:")


def test_ui_market_overview_endpoint(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "skill_id": "ui_market_skill",
                    "description": "Skill for UI market overview",
                    "mode": "prompt",
                    "domain": "market",
                    "version": "1.0.0",
                    "tags": ["ui"],
                    "required_tools": [],
                    "dependencies": [],
                    "prompt_template": "ui {input}",
                }
            ]
        ),
        encoding="utf-8",
    )
    installed_path.write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    app.state.runtime.logger.log("SKILL_MARKET_INSTALL", {"skill_id": "ui_market_skill"})
    client = TestClient(app)
    response = client.get("/ui/market/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["total_listed"] == 1
    assert body["installable_count"] == 1
    assert body["remote_status"]["synced"] is False
    assert any(event["event_type"] == "SKILL_MARKET_INSTALL" for event in body["recent_events"])


def test_ui_ingestion_overview_endpoint(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    ingest1 = client.post("/ingestion/graphify", json={"text": "alpha beta gamma delta"})
    assert ingest1.status_code == 200
    ingest2 = client.post("/ingestion/graphify", json={"text": "alpha beta gamma delta"})
    assert ingest2.status_code == 200

    response = client.get("/ui/ingestion/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["total_ingestions"] == 2
    assert len(body["recent_ingestions"]) >= 2
    assert len(body["recent_dedupe_events"]) >= 1


def test_skills_market_remote_sync_rejects_invalid_signature(tmp_path: Path) -> None:
    storage = tmp_path / ".harness"
    storage.mkdir(parents=True, exist_ok=True)
    registry_path = storage / "market.json"
    installed_path = storage / "installed.json"
    registry_path.write_text(json.dumps([]), encoding="utf-8")
    installed_path.write_text(json.dumps([]), encoding="utf-8")

    signing_key = SigningKey.generate()
    signature_payload = {
        "source": "test-remote",
        "generated_at": "2026-04-10T00:00:00+00:00",
        "signing_version": "v2-ed25519",
        "items": [],
    }
    remote_index = {
        **signature_payload,
        "public_key": signing_key.verify_key.encode(encoder=Base64Encoder).decode("utf-8"),
        "signature": Base64Encoder.encode(b"invalid-signature").decode("utf-8"),
        "index_hash": "sha256:deadbeef",
    }
    remote_index_path = tmp_path / "remote-index-invalid.json"
    remote_index_path.write_text(json.dumps(remote_index), encoding="utf-8")

    (tmp_path / "harness.config.json").write_text(
        json.dumps(
            {
                "skills": {
                    "market_registry_file": "market.json",
                    "market_installed_file": "installed.json",
                }
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_path)
    client = TestClient(app)
    sync = client.post("/skills/market/remote/sync", json={"source": str(remote_index_path)})
    assert sync.status_code == 400


def test_execute_skill_endpoint_prompt_mode() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post("/skills/reactive_chat/execute", json={"input": {"message": "hello"}})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["skill_id"] == "reactive_chat"
    assert body["result"]["mode"] == "prompt"


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


def test_memory_graph_search_endpoint() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.memory.graph_add_node("skill:test_skill", "skill", {"description": "test skill"})
    client = TestClient(app)

    response = client.get("/memory/graph/search?query=test&node_type=skill&limit=10")
    assert response.status_code == 200
    body = response.json()
    assert any(hit["node_id"] == "skill:test_skill" for hit in body)


def test_memory_graph_persists_across_runtime_restart(tmp_path: Path) -> None:
    app1 = create_app(tmp_path)
    app1.state.runtime.memory.graph_add_node("concept:persisted", "concept", {"text": "persisted"})
    app1.state.runtime.memory.graph_add_node("concept:target", "concept", {"text": "target"})
    app1.state.runtime.memory.graph_add_edge("concept:persisted", "concept:target", "related_to")

    app2 = create_app(tmp_path)
    client2 = TestClient(app2)

    neighbors = client2.get("/memory/graph/neighbors?node_id=concept:persisted")
    assert neighbors.status_code == 200
    assert "concept:target" in neighbors.json()["neighbors"]

    search = client2.get("/memory/graph/search?query=persisted&node_type=concept&limit=20")
    assert search.status_code == 200
    assert any(hit["node_id"] == "concept:persisted" for hit in search.json())


def test_ingested_graph_data_persists_across_runtime_restart(tmp_path: Path) -> None:
    app1 = create_app(tmp_path)
    client1 = TestClient(app1)
    ingest = client1.post("/ingestion/graphify", json={"text": "persistent ingestion telemetry graph"})
    assert ingest.status_code == 200
    assert ingest.json()["nodes_added"] > 0

    app2 = create_app(tmp_path)
    client2 = TestClient(app2)
    search = client2.get("/memory/graph/search?query=telemetry&node_type=concept&limit=20")
    assert search.status_code == 200
    assert any("telemetry" in hit["node_id"] for hit in search.json())


def test_memory_graph_migration_export_import_local(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    app.state.runtime.memory.graph_add_node("concept:alpha", "concept", {"text": "alpha"})
    app.state.runtime.memory.graph_add_node("concept:beta", "concept", {"text": "beta"})
    app.state.runtime.memory.graph_add_edge("concept:alpha", "concept:beta", "related_to")

    export_response = client.post(
        "/memory/graph/migration/export",
        json={"backend": "local", "path": ".harness/graph_migration_snapshot.json"},
    )
    assert export_response.status_code == 200
    export_body = export_response.json()
    assert export_body["ok"] is True
    assert export_body["nodes"] >= 2
    assert export_body["edges"] >= 1

    import_response = client.post(
        "/memory/graph/migration/import",
        json={
            "backend": "local",
            "path": ".harness/graph_migration_snapshot.json",
            "clear_existing": True,
        },
    )
    assert import_response.status_code == 200
    import_body = import_response.json()
    assert import_body["ok"] is True
    assert import_body["nodes"] >= 2

    neighbors = client.get("/memory/graph/neighbors?node_id=concept:alpha")
    assert neighbors.status_code == 200
    assert "concept:beta" in neighbors.json()["neighbors"]


def test_emergency_diagnosis_endpoint() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    source_name = "test.emergency.endpoint"
    agent_name = "agent-test-1"
    skill_name = "skill-test-1"
    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": source_name,
            "agent_id": agent_name,
            "skill_id": skill_name,
            "diagnoses": [
                {
                    "hypothesis": "Execution policy blocked the requested tool or command",
                    "confidence": 0.95,
                    "suggested_fix": "Update tool allowlists or execution.allowed_command_prefixes before retrying",
                }
            ],
        },
    )
    client = TestClient(app)

    response = client.get(
        f"/diagnostics/emergency?source={source_name}&agent_id={agent_name}&skill_id={skill_name}&limit=10"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert body["items"][0]["source"] == source_name
    assert body["items"][0]["agent_id"] == agent_name
    assert body["items"][0]["skill_id"] == skill_name
    assert body["items"][0]["diagnoses"][0]["confidence"] == 0.95
    assert "next_offset" in body


def test_emergency_diagnosis_endpoint_supports_offset_and_time_filters() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    for idx in range(3):
        runtime.logger.log(
            "EMERGENCY_DIAGNOSIS",
            {
                "source": "diag-paged-test",
                "agent_id": f"agent-{idx}",
                "skill_id": "skill-paged",
                "diagnoses": [{"hypothesis": f"diag-{idx}", "confidence": 0.5, "suggested_fix": "fix"}],
            },
        )
    client = TestClient(app)

    baseline = client.get("/diagnostics/emergency?source=diag-paged-test&limit=3")
    assert baseline.status_code == 200
    rows = baseline.json()["items"]
    assert len(rows) == 3

    paged = client.get("/diagnostics/emergency?source=diag-paged-test&limit=2&offset=1")
    assert paged.status_code == 200
    paged_body = paged.json()
    paged_rows = paged_body["items"]
    assert len(paged_rows) == 2
    assert paged_rows[-1]["agent_id"] == rows[-2]["agent_id"]
    assert paged_body["has_more"] in [True, False]

    after = rows[1]["timestamp"]
    filtered = client.get(
        "/diagnostics/emergency",
        params={"source": "diag-paged-test", "after": after, "limit": 5},
    )
    assert filtered.status_code == 200
    filtered_rows = filtered.json()["items"]
    assert all(r["timestamp"] >= after for r in filtered_rows)


def test_emergency_analyze_endpoint_returns_fix_plan() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post(
        "/diagnostics/emergency/analyze",
        json={
            "source": "orchestrator.skill_execution",
            "error": "Timed out after 0.01s",
            "agent_id": "agent-x",
            "skill_id": "slow_skill",
            "context": {"task_id": "task-x"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["failure_id"].startswith("failure-")
    assert body["diagnoses"]
    assert body["selected_hypothesis"]
    assert body["consensus"]
    assert body["consensus"][0]["hypothesis"] == body["selected_hypothesis"]
    assert body["consensus"][0]["consensus_score"] >= body["consensus"][-1]["consensus_score"]
    assert body["fix_plan"]["requires_user_approval"] is True
    assert isinstance(body["fix_plan"]["actions"], list)


def test_emergency_fix_apply_requires_approval() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": False,
            "dry_run": True,
            "fix_plan": {
                "failure_id": "failure-test",
                "recommended_hypothesis": "test",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [{"action_type": "restart_module", "target_id": "orchestrator"}],
                "notes": "test",
            },
        },
    )
    assert response.status_code == 400


def test_emergency_fix_apply_updates_config_when_approved() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    old_value = client.get("/config").json()["state_machine.default_budget.max_tokens"]
    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-config",
                "recommended_hypothesis": "Need config update",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 1337},
                    }
                ],
                "notes": "apply config patch",
            },
        },
    )
    assert apply.status_code == 200
    body = apply.json()
    assert body["ok"] is True
    assert body["applied"] is True
    assert body["execution_id"].startswith("fix-")
    assert body["rollback_available"] is True
    assert any(r.get("status") == "applied" for r in body["results"])

    new_value = client.get("/config").json()["state_machine.default_budget.max_tokens"]
    assert new_value == 1337
    assert new_value != old_value


def test_emergency_fix_rollback_restores_config_value() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    before = client.get("/config").json()["state_machine.default_budget.max_tokens"]
    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-rollback-config",
                "recommended_hypothesis": "config drift",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 1777},
                    }
                ],
                "notes": "patch config",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]
    assert execution_id

    changed = client.get("/config").json()["state_machine.default_budget.max_tokens"]
    assert changed == 1777

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200
    rollback_body = rollback.json()
    assert rollback_body["ok"] is True
    assert rollback_body["rolled_back"] is True

    restored = client.get("/config").json()["state_machine.default_budget.max_tokens"]
    assert restored == before


def test_emergency_fix_rollback_restores_tool_policy_state() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    runtime = app.state.runtime

    runtime.tools.policy.blocked_tool_names.discard("shell_command")
    runtime.tools.policy.allowed_tool_names.add("shell_command")

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-rollback-tool",
                "recommended_hypothesis": "tool risk",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [{"action_type": "disable_tool", "target_id": "shell_command"}],
                "notes": "disable tool temporarily",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]
    assert "shell_command" in runtime.tools.policy.blocked_tool_names
    assert "shell_command" not in runtime.tools.policy.allowed_tool_names

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200
    assert "shell_command" not in runtime.tools.policy.blocked_tool_names
    assert "shell_command" in runtime.tools.policy.allowed_tool_names


def test_emergency_fix_execution_query_returns_apply_and_rollback() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-query-fix",
                "recommended_hypothesis": "config drift",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 1888},
                    }
                ],
                "notes": "query coverage",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200

    query = client.get(f"/diagnostics/emergency/fix-executions?execution_id={execution_id}&limit=20")
    assert query.status_code == 200
    body = query.json()
    assert isinstance(body["items"], list)
    event_types = {row["event_type"] for row in body["items"]}
    assert "EMERGENCY_FIX_APPLY" in event_types
    assert "EMERGENCY_FIX_ROLLBACK" in event_types


def test_emergency_fix_execution_export_and_verify() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-export-fix",
                "recommended_hypothesis": "config drift",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 1999},
                    }
                ],
                "notes": "export coverage",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]

    out_path = ".harness/test-fix-executions.json"
    export = client.post(
        "/diagnostics/emergency/fix-executions/export",
        json={"path": out_path, "execution_id": execution_id, "limit": 20},
    )
    assert export.status_code == 200
    export_body = export.json()
    assert export_body["ok"] is True

    verify = client.post(
        "/diagnostics/emergency/fix-executions/verify",
        json={"path": out_path},
    )
    assert verify.status_code == 200
    verify_body = verify.json()
    assert verify_body["valid"] is True
    assert verify_body["stored_hash"] == verify_body["computed_hash"]

    Path(out_path).unlink(missing_ok=True)


def test_api_key_auth_enforced_when_enabled() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("api.require_api_key", True)
    app.state.runtime.config.set("api.api_key", "secret123")
    client = FastAPITestClient(app)

    unauthorized = client.get("/status")
    assert unauthorized.status_code == 401

    authorized = client.get("/status", headers={"x-api-key": "secret123"})
    assert authorized.status_code == 200


def test_admin_api_key_scope_enforced_for_mutating_endpoints() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("api.require_api_key", True)
    app.state.runtime.config.set("api.api_key", "read123")
    app.state.runtime.config.set("api.require_admin_api_key", True)
    app.state.runtime.config.set("api.admin_api_key", "admin123")
    client = FastAPITestClient(app)

    read_ok = client.get("/status", headers={"x-api-key": "read123"})
    assert read_ok.status_code == 200

    admin_blocked = client.post(
        "/config",
        headers={"x-api-key": "read123"},
        json={"key": "state_machine.default_budget.max_tokens", "value": 4096},
    )
    assert admin_blocked.status_code == 401

    admin_ok = client.post(
        "/config",
        headers={"x-api-key": "admin123"},
        json={"key": "state_machine.default_budget.max_tokens", "value": 4096},
    )
    assert admin_ok.status_code == 200


def test_run_history_report_endpoint() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    app.state.runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "orchestrator.skill_execution",
            "agent_id": "subagent-report",
            "skill_id": "slow_skill",
            "diagnoses": [
                {
                    "hypothesis": "orchestrator.skill_execution exceeded its configured execution budget",
                    "confidence": 0.9,
                    "suggested_fix": "Reduce task scope, optimize the handler, or increase orchestrator.skill_execution_timeout_s",
                }
            ],
        },
    )

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
    assert isinstance(body.get("recent_diagnoses"), list)
    assert any(d.get("source") == "orchestrator.skill_execution" for d in body.get("recent_diagnoses", []))
    assert any(d.get("agent_id") == "subagent-report" for d in body.get("recent_diagnoses", []))
    assert any(d.get("skill_id") == "slow_skill" for d in body.get("recent_diagnoses", []))
    assert isinstance(body.get("health"), list)


def test_incident_report_by_agent_id() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200
    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200

    response = client.get(f"/reports/incident?agent_id={agent_id}&limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "agent"
    assert body["agent_id"] == agent_id
    assert body["agent"]["agent_id"] == agent_id
    assert any(log["event_type"] == "AGENT_SKILL_EXECUTED" for log in body["executions"])


def test_incident_report_by_task_id() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    chat = client.post("/chat", json={"prompt": "incident task", "model_backend": "local_stub"})
    assert chat.status_code == 200
    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    task_id = tasks.json()[0]["task_id"]

    response = client.get(f"/reports/incident?task_id={task_id}&limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "task"
    assert body["task_id"] == task_id
    assert body["task"]["task_id"] == task_id
    assert isinstance(body["related_events"], list)


def test_incident_report_by_execution_id() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]
    assert client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]}).status_code == 200

    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200
    execution_id = executed.json()["execution_id"]

    response = client.get(f"/reports/incident?execution_id={execution_id}&limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "execution"
    assert body["execution_id"] == execution_id
    assert body["agent_id"] == agent_id
    assert any(log["payload"].get("execution_id") == execution_id for log in body["executions"])
    assert body["fix_executions"] == []
    assert body["correlation"]["failure_ids"] == []
    assert body["correlation"]["fix_execution_count"] == 0
    assert body["correlation"]["correlation_sources"] == ["from_execution_id"]
    assert body["correlation"]["resolved_execution_ids"] == []


def test_incident_report_includes_fix_execution_records_for_fix_execution_id() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-incident-fix",
                "recommended_hypothesis": "policy drift",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2111},
                    }
                ],
                "notes": "incident report coverage",
            },
        },
    )
    assert apply.status_code == 200
    fix_execution_id = apply.json()["execution_id"]

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": fix_execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200

    response = client.get(f"/reports/incident?execution_id={fix_execution_id}&limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "execution"
    assert body["execution_id"] == fix_execution_id
    event_types = {row["event_type"] for row in body["fix_executions"]}
    assert "EMERGENCY_FIX_APPLY" in event_types
    assert "EMERGENCY_FIX_ROLLBACK" in event_types
    assert "from_execution_id" in body["correlation"]["correlation_sources"]
    assert fix_execution_id in body["correlation"]["resolved_execution_ids"]


def test_incident_report_by_agent_correlates_fix_executions_by_failure_id() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    analyzed = client.post(
        "/diagnostics/emergency/analyze",
        json={
            "source": "orchestrator.skill_execution",
            "error": "Timed out after 0.01s",
            "agent_id": agent_id,
            "skill_id": "slow_skill",
            "context": {"task_id": "task-correlated"},
        },
    )
    assert analyzed.status_code == 200
    failure_id = analyzed.json()["failure_id"]

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": failure_id,
                "recommended_hypothesis": "execution timeout",
                "risk_level": "medium",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2222},
                    }
                ],
                "notes": "correlate by failure id",
            },
        },
    )
    assert apply.status_code == 200
    fix_execution_id = apply.json()["execution_id"]

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": fix_execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200

    report = client.get(f"/reports/incident?agent_id={agent_id}&limit=20")
    assert report.status_code == 200
    body = report.json()
    event_types = {row["event_type"] for row in body["fix_executions"]}
    assert "EMERGENCY_FIX_APPLY" in event_types
    assert "EMERGENCY_FIX_ROLLBACK" in event_types
    assert any(row["payload"].get("execution_id") == fix_execution_id for row in body["fix_executions"])
    assert failure_id in body["correlation"]["failure_ids"]
    assert body["correlation"]["fix_execution_count"] >= 2
    assert "from_failure_id" in body["correlation"]["correlation_sources"]
    assert fix_execution_id in body["correlation"]["resolved_execution_ids"]


def test_incident_report_can_exclude_fix_executions() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-filter-no-fix",
                "recommended_hypothesis": "config drift",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2333},
                    }
                ],
                "notes": "exclude fix executions",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]

    report = client.get(f"/reports/incident?execution_id={execution_id}&include_fix_executions=false&limit=20")
    assert report.status_code == 200
    body = report.json()
    assert body["fix_executions"] == []
    assert body["correlation"]["fix_execution_count"] == 0
    assert body["correlation"]["resolved_execution_ids"] == []
    assert "fix_executions_excluded_by_filter" in body["correlation"]["warnings"]


def test_incident_report_can_filter_fix_event_type() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-filter-event-type",
                "recommended_hypothesis": "config drift",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2444},
                    }
                ],
                "notes": "event type filter",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]

    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200

    report = client.get(f"/reports/incident?execution_id={execution_id}&fix_event_type=rollback&limit=20")
    assert report.status_code == 200
    body = report.json()
    assert body["fix_executions"]
    assert all(row["event_type"] == "EMERGENCY_FIX_ROLLBACK" for row in body["fix_executions"])
    assert "fix_event_type_filtered:rollback" in body["correlation"]["warnings"]


def test_incident_report_correlation_warns_when_multiple_failure_ids_present() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    runtime = app.state.runtime

    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "warning.test",
            "agent_id": "main-agent",
            "failure_id": "failure-a",
            "diagnoses": [
                {
                    "hypothesis": "Execution timeout",
                    "confidence": 0.8,
                    "suggested_fix": "Increase timeout",
                }
            ],
        },
    )
    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "warning.test",
            "agent_id": "main-agent",
            "failure_id": "failure-b",
            "diagnoses": [
                {
                    "hypothesis": "Policy mismatch",
                    "confidence": 0.7,
                    "suggested_fix": "Align tool policy",
                }
            ],
        },
    )

    report = client.get("/reports/incident?agent_id=main-agent&limit=20")
    assert report.status_code == 200
    body = report.json()
    assert set(body["correlation"]["failure_ids"]) == {"failure-a", "failure-b"}
    assert "multiple_failure_ids_detected" in body["correlation"]["warnings"]


def test_incident_report_export_and_verify() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200
    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200

    out_path = ".harness/test-incident-export.json"
    export = client.post("/reports/incident/export", json={"path": out_path, "agent_id": agent_id, "limit": 20})
    assert export.status_code == 200
    body = export.json()
    assert body["ok"] is True

    target = Path(out_path)
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["report_hash"] == body["report_hash"]

    verify = client.post("/reports/incident/verify", json={"path": out_path})
    assert verify.status_code == 200
    verify_body = verify.json()
    assert verify_body["valid"] is True
    assert verify_body["stored_hash"] == verify_body["computed_hash"]

    target.unlink(missing_ok=True)


def test_incident_report_verify_detects_tamper() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    chat = client.post("/chat", json={"prompt": "tamper incident", "model_backend": "local_stub"})
    assert chat.status_code == 200
    task_id = client.get("/tasks").json()[0]["task_id"]
    out_path = ".harness/test-incident-tamper.json"
    export = client.post("/reports/incident/export", json={"path": out_path, "task_id": task_id, "limit": 20})
    assert export.status_code == 200

    target = Path(out_path)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    loaded["scope"] = "tampered"
    target.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verify = client.post("/reports/incident/verify", json={"path": out_path})
    assert verify.status_code == 200
    body = verify.json()
    assert body["valid"] is False
    assert body["stored_hash"] != body["computed_hash"]

    target.unlink(missing_ok=True)


def test_incident_report_export_verify_with_include_fix_executions_false() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-export-filter-none",
                "recommended_hypothesis": "config drift",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2555},
                    }
                ],
                "notes": "export no fix executions",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]

    out_path = ".harness/test-incident-export-no-fix.json"
    export = client.post(
        "/reports/incident/export",
        json={
            "path": out_path,
            "execution_id": execution_id,
            "include_fix_executions": False,
            "limit": 20,
        },
    )
    assert export.status_code == 200

    loaded = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert loaded["fix_executions"] == []
    assert loaded["correlation"]["fix_execution_count"] == 0

    verify = client.post("/reports/incident/verify", json={"path": out_path})
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    Path(out_path).unlink(missing_ok=True)


def test_incident_report_export_verify_with_fix_event_type_rollback() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    apply = client.post(
        "/diagnostics/emergency/fix-apply",
        json={
            "approved": True,
            "dry_run": False,
            "fix_plan": {
                "failure_id": "failure-export-filter-rollback",
                "recommended_hypothesis": "config drift",
                "risk_level": "low",
                "requires_user_approval": True,
                "actions": [
                    {
                        "action_type": "update_config",
                        "params": {"key": "state_machine.default_budget.max_tokens", "value": 2666},
                    }
                ],
                "notes": "export rollback only",
            },
        },
    )
    assert apply.status_code == 200
    execution_id = apply.json()["execution_id"]
    rollback = client.post(
        "/diagnostics/emergency/fix-rollback",
        json={"execution_id": execution_id, "dry_run": False},
    )
    assert rollback.status_code == 200

    out_path = ".harness/test-incident-export-rollback-only.json"
    export = client.post(
        "/reports/incident/export",
        json={
            "path": out_path,
            "execution_id": execution_id,
            "include_fix_executions": True,
            "fix_event_type": "rollback",
            "limit": 20,
        },
    )
    assert export.status_code == 200

    loaded = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert loaded["fix_executions"]
    assert all(row["event_type"] == "EMERGENCY_FIX_ROLLBACK" for row in loaded["fix_executions"])

    verify = client.post("/reports/incident/verify", json={"path": out_path})
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    Path(out_path).unlink(missing_ok=True)


def test_emergency_diagnosis_export_and_verify() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    client = TestClient(app)
    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "test.snapshot",
            "agent_id": "agent-snap",
            "skill_id": "skill-snap",
            "diagnoses": [
                {
                    "hypothesis": "Execution policy blocked the requested tool or command",
                    "confidence": 0.95,
                    "suggested_fix": "Update tool allowlists or execution.allowed_command_prefixes before retrying",
                }
            ],
        },
    )

    out_path = ".harness/test-diagnosis-snapshot.json"
    export = client.post(
        "/diagnostics/emergency/export",
        json={"path": out_path, "source": "test.snapshot", "agent_id": "agent-snap", "limit": 20},
    )
    assert export.status_code == 200
    body = export.json()
    assert body["ok"] is True

    target = Path(out_path)
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["report_hash"] == body["report_hash"]

    verify = client.post("/diagnostics/emergency/verify", json={"path": out_path})
    assert verify.status_code == 200
    verify_body = verify.json()
    assert verify_body["valid"] is True
    assert verify_body["stored_hash"] == verify_body["computed_hash"]

    target.unlink(missing_ok=True)


def test_emergency_diagnosis_export_empty_page_and_verify() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    out_path = ".harness/test-diagnosis-empty-snapshot.json"
    export = client.post(
        "/diagnostics/emergency/export",
        json={"path": out_path, "source": "no.such.source", "limit": 20},
    )
    assert export.status_code == 200
    body = export.json()
    assert body["ok"] is True

    target = Path(out_path)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["items"] == []
    assert loaded["has_more"] is False
    assert loaded["next_offset"] is None

    verify = client.post("/diagnostics/emergency/verify", json={"path": out_path})
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    target.unlink(missing_ok=True)


def test_emergency_diagnosis_export_limit_boundary_500() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    client = TestClient(app)
    source_name = f"diag-limit-500-{time.time_ns()}"

    for idx in range(500):
        runtime.logger.log(
            "EMERGENCY_DIAGNOSIS",
            {
                    "source": source_name,
                "agent_id": f"agent-{idx}",
                "skill_id": "skill-limit",
                "diagnoses": [{"hypothesis": "ok", "confidence": 0.5, "suggested_fix": "none"}],
            },
        )

    out_path = ".harness/test-diagnosis-limit-500.json"
    export = client.post(
        "/diagnostics/emergency/export",
        json={"path": out_path, "source": source_name, "limit": 500},
    )
    assert export.status_code == 200

    target = Path(out_path)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["limit"] == 500
    assert len(loaded["items"]) == 500
    assert loaded["has_more"] is False

    target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# P4-01 Graphify Ingestion MVP
# ---------------------------------------------------------------------------

def test_ingestion_graphify_creates_nodes_and_edges(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "Memory management enables efficient knowledge retrieval across multiple sessions"
    response = client.post("/ingestion/graphify", json={"text": text, "metadata": {"source": "test"}})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["nodes_added"] > 0
    assert body["edges_added"] > 0
    assert isinstance(body["node_ids"], list)
    assert all(nid.startswith("concept:") for nid in body["node_ids"])


def test_ingestion_graphify_nodes_appear_in_graph_search(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "Planning orchestration enables autonomous agent scheduling"
    client.post("/ingestion/graphify", json={"text": text})
    search = client.get("/memory/graph/search?query=orchestration&node_type=concept&limit=10")
    assert search.status_code == 200
    hits = search.json()
    assert any("orchestration" in h["node_id"] for h in hits)


def test_ingestion_graphify_filters_short_words_and_stopwords(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    # "the", "and", "or", "in" are stopwords; "go" is too short
    text = "the and or in go"
    response = client.post("/ingestion/graphify", json={"text": text})
    assert response.status_code == 200
    body = response.json()
    assert body["nodes_added"] == 0
    assert body["edges_added"] == 0


def test_ingestion_stats_aggregates_ingestion_events(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    # Two separate ingestions
    client.post("/ingestion/graphify", json={"text": "autonomous memory retrieval pipeline"})
    client.post("/ingestion/graphify", json={"text": "diagnostic failure correlation tracing"})
    stats = client.get("/ingestion/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_ingestions"] == 2
    assert body["total_nodes_added"] > 0
    assert body["total_edges_added"] > 0
    assert body["last_ingested_at"] is not None


def test_ingestion_stats_zero_when_no_ingestions(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    stats = client.get("/ingestion/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_ingestions"] == 0
    assert body["total_nodes_added"] == 0
    assert body["total_edges_added"] == 0
    assert body["last_ingested_at"] is None


def test_ingestion_graphify_emits_ingestion_complete_log_event(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    runtime = app.state.runtime
    client = TestClient(app)
    text = "knowledge graph ingestion pipeline verification"
    client.post("/ingestion/graphify", json={"text": text})
    rows = runtime.logger.query(event_type="INGESTION_COMPLETE", limit=10)
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["nodes_added"] > 0
    assert isinstance(payload["node_ids"], list)


# ---------------------------------------------------------------------------
# P4-02 Ingestion dedupe and confidence policy
# ---------------------------------------------------------------------------

def test_ingestion_dedupe_suppresses_existing_nodes(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "knowledge graph ingestion pipeline"
    # First ingest — all nodes should be new
    r1 = client.post("/ingestion/graphify", json={"text": text})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["nodes_added"] > 0
    assert b1["nodes_skipped"] == 0

    # Second ingest same text — all nodes already exist
    r2 = client.post("/ingestion/graphify", json={"text": text})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["nodes_added"] == 0
    assert b2["nodes_skipped"] == b1["nodes_added"]


def test_ingestion_dedupe_suppresses_existing_edges(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "memory retrieval pipeline management"
    r1 = client.post("/ingestion/graphify", json={"text": text})
    assert r1.json()["edges_added"] > 0
    assert r1.json()["edges_skipped"] == 0

    r2 = client.post("/ingestion/graphify", json={"text": text})
    assert r2.json()["edges_added"] == 0
    assert r2.json()["edges_skipped"] > 0


def test_ingestion_dedupe_emits_audit_log_events(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    runtime = app.state.runtime
    client = TestClient(app)
    text = "planning orchestration memory management"
    client.post("/ingestion/graphify", json={"text": text})
    # Second run creates INGESTION_DEDUPE events
    client.post("/ingestion/graphify", json={"text": text})
    rows = runtime.logger.query(event_type="INGESTION_DEDUPE", limit=100)
    assert len(rows) > 0
    for row in rows:
        assert row["payload"]["reason"] == "already_exists"
        assert "node_id" in row["payload"]
        assert "confidence" in row["payload"]


def test_ingestion_dedupe_log_endpoint_returns_entries(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "autonomous agent scheduling pipeline"
    client.post("/ingestion/graphify", json={"text": text})
    client.post("/ingestion/graphify", json={"text": text})
    resp = client.get("/ingestion/dedupe-log?limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"]
    assert all(e["reason"] == "already_exists" for e in body["items"])
    assert all(e["node_id"].startswith("concept:") for e in body["items"])


def test_ingestion_dedupe_log_filters_by_reason(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "memory graph retrieval pipeline"
    client.post("/ingestion/graphify", json={"text": text})
    client.post("/ingestion/graphify", json={"text": text})
    resp = client.get("/ingestion/dedupe-log?reason=already_exists")
    assert resp.status_code == 200
    assert resp.json()["items"]
    resp_empty = client.get("/ingestion/dedupe-log?reason=below_confidence_threshold")
    assert resp_empty.json()["items"] == []


def test_ingestion_confidence_min_suppresses_low_frequency_concepts(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    # confidence_min = 0.5 means a concept must make up ≥50% of concept tokens — very aggressive
    # Use a text where one concept dominates: "memory memory memory noise"
    app.state.runtime.config.set("ingestion.confidence_min", 0.5)
    client = TestClient(app)
    # "memory" appears 3 times, "noise" once — out of 4 total concept tokens
    # memory confidence = 3/4 = 0.75 ≥ 0.5 → included
    # noise confidence = 1/4 = 0.25 < 0.5 → skipped
    text = "memory memory memory noise"
    r = client.post("/ingestion/graphify", json={"text": text})
    assert r.status_code == 200
    body = r.json()
    assert "concept:memory" in body["node_ids"]
    assert "concept:noise" not in body["node_ids"]
    assert body["nodes_skipped"] >= 1


def test_ingestion_stats_tracks_skipped_counts(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    text = "knowledge graph pipeline retrieval"
    client.post("/ingestion/graphify", json={"text": text})
    client.post("/ingestion/graphify", json={"text": text})
    stats = client.get("/ingestion/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_nodes_skipped"] > 0
    assert body["total_edges_skipped"] > 0


def test_incident_report_unknown_execution_id_returns_404() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.get("/reports/incident?execution_id=exec-does-not-exist")
    assert response.status_code == 404


def test_export_rejects_invalid_time_window() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post(
        "/diagnostics/emergency/export",
        json={
            "path": ".harness/test-invalid-window.json",
            "source": "diag",
            "after": "2026-04-10T23:59:59+00:00",
            "before": "2026-04-10T00:00:00+00:00",
            "limit": 10,
        },
    )
    assert response.status_code == 400


def test_api_helper_get_incident_by_execution_id() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]
    assert client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]}).status_code == 200

    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200
    execution_id = executed.json()["execution_id"]

    helper = HarnessApiClient(base_url="http://testserver", client=client)
    incident = helper.get_incident_by_execution_id(execution_id=execution_id, limit=20)
    assert incident["execution_id"] == execution_id
    assert incident["agent_id"] == agent_id


def test_api_helper_export_and_verify_diagnosis_snapshot() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    client = TestClient(app)
    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "helper.snapshot",
            "agent_id": "agent-helper",
            "skill_id": "skill-helper",
            "diagnoses": [
                {
                    "hypothesis": "Execution policy blocked",
                    "confidence": 0.95,
                    "suggested_fix": "Update allowlist",
                }
            ],
        },
    )

    helper = HarnessApiClient(base_url="http://testserver", client=client)
    out_path = ".harness/test-helper-diagnosis-snapshot.json"
    exported = helper.export_diagnosis_snapshot(path=out_path, source="helper.snapshot", limit=20)
    assert exported["ok"] is True
    verified = helper.verify_diagnosis_snapshot(path=out_path)
    assert verified["valid"] is True

    Path(out_path).unlink(missing_ok=True)


def test_api_helper_ui_overviews_and_market_status(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    helper = HarnessApiClient(base_url="http://testserver", client=client)

    # Seed market and ingestion activity so overview endpoints have meaningful payloads.
    app.state.runtime.logger.log("SKILL_MARKET_INSTALL", {"skill_id": "seed-skill"})
    ingest = client.post("/ingestion/graphify", json={"text": "alpha beta gamma delta"})
    assert ingest.status_code == 200

    market_overview = helper.get_ui_market_overview()
    ingestion_overview = helper.get_ui_ingestion_overview()
    remote_status = helper.get_market_remote_status()

    assert "total_listed" in market_overview
    assert "recent_events" in market_overview
    assert isinstance(market_overview["recent_events"], list)

    assert "stats" in ingestion_overview
    assert ingestion_overview["stats"]["total_ingestions"] >= 1
    assert isinstance(ingestion_overview["recent_ingestions"], list)

    assert "synced" in remote_status


def test_diagnostics_query_latency_guardrail() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    client = TestClient(app)
    source_name = f"diag-latency-{time.time_ns()}"

    for idx in range(300):
        runtime.logger.log(
            "EMERGENCY_DIAGNOSIS",
            {
                "source": source_name,
                "agent_id": f"agent-lat-{idx}",
                "skill_id": "skill-lat",
                "diagnoses": [{"hypothesis": "h", "confidence": 0.5, "suggested_fix": "s"}],
            },
        )

    started = time.perf_counter()
    response = client.get(f"/diagnostics/emergency?source={source_name}&offset=100&limit=100")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert len(response.json()["items"]) == 100
    assert elapsed < 1.5


def test_incident_report_latency_guardrail() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    spawned = client.post("/agents/spawn", json={"description": "Need shell execution support", "role": "Exec"})
    assert spawned.status_code == 200
    agent_id = spawned.json()["agent_id"]
    assert client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]}).status_code == 200

    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert executed.status_code == 200
    execution_id = executed.json()["execution_id"]

    started = time.perf_counter()
    response = client.get(f"/reports/incident?execution_id={execution_id}&limit=50")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert response.json()["execution_id"] == execution_id
    assert elapsed < 1.5


def test_emergency_diagnosis_verify_detects_tamper() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    client = TestClient(app)
    runtime.logger.log(
        "EMERGENCY_DIAGNOSIS",
        {
            "source": "test.snapshot.tamper",
            "diagnoses": [
                {
                    "hypothesis": "Failure observed",
                    "confidence": 0.3,
                    "suggested_fix": "Inspect logs",
                }
            ],
        },
    )

    out_path = ".harness/test-diagnosis-snapshot-tamper.json"
    export = client.post(
        "/diagnostics/emergency/export",
        json={"path": out_path, "source": "test.snapshot.tamper", "limit": 20},
    )
    assert export.status_code == 200

    target = Path(out_path)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    loaded["source"] = "tampered"
    target.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verify = client.post("/diagnostics/emergency/verify", json={"path": out_path})
    assert verify.status_code == 200
    body = verify.json()
    assert body["valid"] is False
    assert body["stored_hash"] != body["computed_hash"]

    target.unlink(missing_ok=True)


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
    assert isinstance(body.get("max_export_bytes"), int)


def test_run_history_export_endpoint_writes_file() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    out_path = ".harness/test-run-history-export.json"
    response = client.post(
        "/reports/run-history/export",
        json={"path": out_path, "task_limit": 5, "log_limit": 20},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    target = Path(out_path)
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["report_hash"] == body["report_hash"]

    target.unlink(missing_ok=True)


def test_run_history_export_endpoint_blocks_path_outside_policy() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post(
        "/reports/run-history/export",
        json={"path": "../outside-policy-report.json", "task_limit": 5, "log_limit": 20},
    )
    assert response.status_code == 403


def test_run_history_export_endpoint_respects_max_bytes() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("reports.max_export_bytes", 64)
    client = TestClient(app, normalize_runtime=False)

    response = client.post(
        "/reports/run-history/export",
        json={"path": ".harness/too-large-export.json", "task_limit": 10, "log_limit": 50},
    )
    assert response.status_code == 413


def test_run_history_verify_endpoint_valid_report() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    out_path = ".harness/test-run-history-verify-valid.json"
    export = client.post(
        "/reports/run-history/export",
        json={"path": out_path, "task_limit": 5, "log_limit": 20},
    )
    assert export.status_code == 200

    verify = client.post("/reports/run-history/verify", json={"path": out_path})
    assert verify.status_code == 200
    body = verify.json()
    assert body["valid"] is True
    assert body["stored_hash"] == body["computed_hash"]

    Path(out_path).unlink(missing_ok=True)


def test_run_history_verify_endpoint_detects_tamper() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    out_path = ".harness/test-run-history-verify-tampered.json"
    export = client.post(
        "/reports/run-history/export",
        json={"path": out_path, "task_limit": 5, "log_limit": 20},
    )
    assert export.status_code == 200

    target = Path(out_path)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    loaded["total_tasks"] = int(loaded.get("total_tasks", 0)) + 1
    target.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verify = client.post("/reports/run-history/verify", json={"path": out_path})
    assert verify.status_code == 200
    body = verify.json()
    assert body["valid"] is False
    assert body["stored_hash"] != body["computed_hash"]

    target.unlink(missing_ok=True)


def test_artifacts_cleanup_dry_run_lists_old_report_without_deleting() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    target = Path(".harness/cleanup-dry-run.json")
    target.write_text("{}\n", encoding="utf-8")
    old_ts = time.time() - (10 * 24 * 60 * 60)
    os.utime(target, (old_ts, old_ts))

    response = client.post(
        "/artifacts/cleanup",
        json={"max_age_days": 7, "dry_run": True, "include_logs": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert str(target.resolve()) in body["deleted_paths"]
    assert target.exists()

    target.unlink(missing_ok=True)


def test_artifacts_cleanup_deletes_old_report_file() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    target = Path(".harness/cleanup-delete.json")
    target.write_text("{}\n", encoding="utf-8")
    old_ts = time.time() - (10 * 24 * 60 * 60)
    os.utime(target, (old_ts, old_ts))

    response = client.post(
        "/artifacts/cleanup",
        json={"max_age_days": 7, "dry_run": False, "include_logs": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert str(target.resolve()) in body["deleted_paths"]
    assert not target.exists()


def test_roles_templates_endpoint_returns_superpowered_roles() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.get("/roles/templates")
    assert response.status_code == 200
    body = response.json()
    role_keys = {row["role_key"] for row in body}
    assert {"implementer", "spec_reviewer", "code_reviewer", "verifier"}.issubset(role_keys)


def test_chat_superpowered_blocks_without_required_approvals() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)
    approvals_path = Path(".harness/approvals.json")
    original_approvals: str | None = None
    if approvals_path.exists():
        original_approvals = approvals_path.read_text(encoding="utf-8")
        approvals_path.unlink()

    try:
        response = client.post(
            "/chat",
            json={
                "prompt": "Build a new workflow module",
                "model_backend": "local_stub",
                "workflow_mode": "superpowered",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["mode"] == "approval-gate"
        assert "Missing approvals" in body["response"]
        assert body["workflow_mode"] == "superpowered"
        assert body["missing_approvals"] == ["spec", "plan"]
        assert "required_skill_chain" in body

        tasks = client.get("/tasks")
        assert tasks.status_code == 200
        task_id = tasks.json()[0]["task_id"]
        detail = client.get(f"/tasks/{task_id}")
        assert detail.status_code == 200
        output = detail.json()["output"]
        assert output["workflow_mode"] == "superpowered"
        assert output["missing_approvals"] == ["spec", "plan"]
    finally:
        if original_approvals is not None:
            approvals_path.parent.mkdir(parents=True, exist_ok=True)
            approvals_path.write_text(original_approvals, encoding="utf-8")
        elif approvals_path.exists():
            approvals_path.unlink()


def test_chat_superpowered_review_loop_attaches_review_result() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "prompt": "Build a new workflow module",
            "model_backend": "local_stub",
            "workflow_mode": "superpowered",
            "spec_approved": True,
            "plan_approved": True,
            "plan_tasks": [
                {"title": "Create API endpoint"},
                {"title": "Add task panel"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    task_id = tasks.json()[0]["task_id"]
    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    output = detail.json()["output"]
    assert output["mode"] == "reactive"
    assert output["review_result"]["ok"] is True
    assert len(output["review_result"]["task_results"]) == 2


def test_artifact_lifecycle_approve_and_revoke() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    specs_dir = Path("documents/specs")
    plans_dir = Path("documents/plans")
    specs_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    spec_file = specs_dir / "smoke-spec.txt"
    plan_file = plans_dir / "smoke-plan.txt"
    approvals_path = Path(".harness/approvals.json")
    original_approvals: str | None = None
    if approvals_path.exists():
        original_approvals = approvals_path.read_text(encoding="utf-8")
        approvals_path.unlink()

    try:
        spec_file.write_text("spec content\n", encoding="utf-8")
        plan_file.write_text("plan content\n", encoding="utf-8")

        list_before = client.get("/artifacts")
        assert list_before.status_code == 200
        by_type_before = {row["artifact_type"]: row for row in list_before.json() if row["filename"].startswith("smoke-")}
        assert by_type_before["spec"]["approved"] is False
        assert by_type_before["plan"]["approved"] is False

        approve_spec = client.post("/artifacts/approve", json={"artifact_type": "spec"})
        assert approve_spec.status_code == 200
        assert approve_spec.json()["approved"] is True

        list_after_approve = client.get("/artifacts")
        assert list_after_approve.status_code == 200
        by_type_after = {row["artifact_type"]: row for row in list_after_approve.json() if row["filename"].startswith("smoke-")}
        assert by_type_after["spec"]["approved"] is True

        revoke_spec = client.delete("/artifacts/approve?artifact_type=spec")
        assert revoke_spec.status_code == 200
        assert revoke_spec.json()["approved"] is False
    finally:
        spec_file.unlink(missing_ok=True)
        plan_file.unlink(missing_ok=True)
        if original_approvals is not None:
            approvals_path.parent.mkdir(parents=True, exist_ok=True)
            approvals_path.write_text(original_approvals, encoding="utf-8")
        else:
            approvals_path.unlink(missing_ok=True)


def test_workflow_metrics_endpoint_reports_lightning_and_superpowered() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    lightning = client.post(
        "/chat",
        json={
            "prompt": "Say hello from lightning",
            "model_backend": "local_stub",
            "workflow_mode": "lightning",
        },
    )
    assert lightning.status_code == 200

    superpowered = client.post(
        "/chat",
        json={
            "prompt": "Execute superpowered test task",
            "model_backend": "local_stub",
            "workflow_mode": "superpowered",
            "spec_approved": True,
            "plan_approved": True,
            "plan_tasks": [
                {
                    "title": "Implement deterministic task",
                    "implementer_status": "DONE",
                    "spec_review_passed": True,
                    "code_review_passed": True,
                    "verification_passed": True,
                }
            ],
        },
    )
    assert superpowered.status_code == 200

    metrics = client.get("/metrics/workflow")
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["total_tasks"] >= 2
    assert body["lightning"]["total_tasks"] >= 1
    assert body["superpowered"]["total_tasks"] >= 1
    assert body["superpowered"]["review_ran_count"] >= 1


def test_lmstudio_adapter_parses_pseudo_tool_call_content() -> None:
    adapter = LMStudioAdapter(
        base_url="http://127.0.0.1:1234/v1",
        default_model="test-model",
    )

    parsed = adapter._extract_pseudo_tool_calls(
        '<|tool_call|>call:web_search_basic(query: "current weather in Brooklyn, New York")<|tool_call|>'
    )

    assert len(parsed) == 1
    assert parsed[0].name == "web_search_basic"
    assert parsed[0].arguments == {"query": "current weather in Brooklyn, New York"}


def test_openai_compatible_adapter_parses_pseudo_tool_call_content() -> None:
    adapter = CloudOpenAIAdapter(
        base_url="https://example.com/v1",
        default_model="test-model",
        provider_name="Test OpenAI-compatible",
    )

    parsed = adapter._extract_pseudo_tool_calls(
        '<tool_call>call:web_fetch(url: "https://example.org", timeout_s: 12)</tool_call>'
    )

    assert len(parsed) == 1
    assert parsed[0].name == "web_fetch"
    assert parsed[0].arguments == {"url": "https://example.org", "timeout_s": 12}

