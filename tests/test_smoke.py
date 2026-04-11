from pathlib import Path
import asyncio
import json
import os
import time
from fastapi.testclient import TestClient

from harness.api.server import create_app
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.runtime.bootstrap import build_runtime
from harness.model.adapter import ModelRegistry
from harness.runtime.config import ConfigManager
from harness.scheduler.module import ScheduledJob, Scheduler
from harness.runtime.types import Task
from harness.skills.registry import SkillDefinition
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


def test_logs_endpoint_supports_offset_and_time_filters() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    for idx in range(3):
        runtime.logger.log("TEST_PAGED_LOG", {"source": "paged-test", "idx": idx})
    client = TestClient(app)

    baseline = client.get("/logs?event_type=TEST_PAGED_LOG&source=paged-test&limit=3")
    assert baseline.status_code == 200
    rows = baseline.json()
    assert len(rows) == 3

    paged = client.get("/logs?event_type=TEST_PAGED_LOG&source=paged-test&limit=2&offset=1")
    assert paged.status_code == 200
    paged_rows = paged.json()
    assert len(paged_rows) == 2
    assert paged_rows[-1]["payload"]["idx"] == rows[-2]["payload"]["idx"]

    after = rows[1]["timestamp"]
    filtered = client.get(
        "/logs",
        params={"event_type": "TEST_PAGED_LOG", "source": "paged-test", "after": after, "limit": 5},
    )
    assert filtered.status_code == 200
    filtered_rows = filtered.json()
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
        json={"input": {"command": "where python"}},
    )
    assert forbidden.status_code == 403

    assigned = client.post(f"/agents/{agent_id}/skills/assign", json={"skill_ids": ["safe_shell_command"]})
    assert assigned.status_code == 200

    executed = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "where python"}},
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["ok"] is True
    assert body["execution_id"].startswith("exec-")
    assert body["agent_id"] == agent_id
    assert body["skill_id"] == "safe_shell_command"

    logs = client.get("/logs?event_type=AGENT_SKILL_EXECUTED&limit=5")
    assert logs.status_code == 200
    log_rows = logs.json()
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
    client = TestClient(app)

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
    rows = diag_logs.json()
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
        json={"input": {"command": "where python"}},
    )
    assert blocked.status_code == 403

    diag_logs = client.get("/logs?event_type=EMERGENCY_DIAGNOSIS&limit=10")
    assert diag_logs.status_code == 200
    rows = diag_logs.json()
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
    assert body
    assert body[0]["source"] == source_name
    assert body[0]["agent_id"] == agent_name
    assert body[0]["skill_id"] == skill_name
    assert body[0]["diagnoses"][0]["confidence"] == 0.95


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
    rows = baseline.json()
    assert len(rows) == 3

    paged = client.get("/diagnostics/emergency?source=diag-paged-test&limit=2&offset=1")
    assert paged.status_code == 200
    paged_rows = paged.json()
    assert len(paged_rows) == 2
    assert paged_rows[-1]["agent_id"] == rows[-2]["agent_id"]

    after = rows[1]["timestamp"]
    filtered = client.get(
        "/diagnostics/emergency",
        params={"source": "diag-paged-test", "after": after, "limit": 5},
    )
    assert filtered.status_code == 200
    filtered_rows = filtered.json()
    assert all(r["timestamp"] >= after for r in filtered_rows)


def test_api_key_auth_enforced_when_enabled() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("api.require_api_key", True)
    app.state.runtime.config.set("api.api_key", "secret123")
    client = TestClient(app)

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
    client = TestClient(app)

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
        json={"input": {"command": "where python"}},
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
    client = TestClient(app)

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

