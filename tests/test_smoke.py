from pathlib import Path
import asyncio
import hashlib
import json
import os
import re
import shutil
import time

from nacl.encoding import Base64Encoder
from nacl.signing import SigningKey
from fastapi.testclient import TestClient as FastAPITestClient

from harness.api.client import HarnessApiClient
from harness.api.server import create_app
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionDeniedError, ExecutionModule, ExecutionResult
from harness.runtime.bootstrap import build_runtime
from harness.model.adapter import CloudOpenAIAdapter, LMStudioAdapter, ModelRegistry, ModelResponse, ToolCall
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


CAMOFOX_REDDIT_PROMPT = (
    'If the file "reddit.txt" does not exist in our workspace directory, then create it. '
    "Use the repo camofox tool and skill for browsing. and go to reddit. "
    "use append_file tool to add exactly one new line in that text file. writing the link to the first post you see on the reddit website on a new line in that text file. "
    "After writing, use read_file on reddit.txt and return the full final file content. "
    "Also return the exact tools_used list."
)


def test_defaults_load() -> None:
    cfg = ConfigManager(Path("."))
    assert cfg.get("memory.graph_backend") == "networkx"
    assert cfg.get("tools.deny_all_by_default") is False


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


def test_generate_report_tool_emits_artifact_metadata() -> None:
    runtime = build_runtime(Path(".").resolve())
    result = asyncio.run(
        runtime.tools.execute_tool(
            "generate_report",
            {
                "title": "Artifact Smoke",
                "format": "markdown",
                "target_path": "tmp/artifact-smoke",
                "sections": [
                    {"heading": "Overview", "body": "hello world"},
                    {"heading": "Details", "body": "deterministic output"},
                ],
                "overwrite": True,
            },
        )
    )

    assert result["ok"] is True
    artifacts = result.get("artifacts")
    assert isinstance(artifacts, list)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["generator"] == "generate_report"
    assert artifact["backend"] == "document_backend"
    assert artifact["mime_type"] == "text/markdown"
    assert Path(artifact["path"]).exists()


def test_artifact_preview_endpoint_serves_safe_artifact() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app, normalize_runtime=False)
    root = Path(".").resolve()
    artifact_dir = root / ".titantshift" / "artifacts" / "task-preview-smoke" / "artifact-preview-smoke"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifact_dir / "output.md"
    output_path.write_text("# Preview Smoke\n", encoding="utf-8")
    (artifact_dir / "artifact.json").write_text(
        json.dumps(
            {
                "artifact_id": "artifact-preview-smoke",
                "mime_type": "text/markdown",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get("/artifacts/run/task-preview-smoke/artifact-preview-smoke/preview")
    assert response.status_code == 200
    assert "text/markdown" in response.headers.get("content-type", "")
    assert "Preview Smoke" in response.text


def test_read_file_tool_returns_line_range_and_stats() -> None:
    runtime = build_runtime(Path(".").resolve())
    # Write a temp file inside the allowed workspace
    workspace_tmp = Path(".harness/test-phase2-read.txt")
    workspace_tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        workspace_tmp.write_text("".join(f"line {i}\n" for i in range(1, 21)), encoding="utf-8")

        # Full read
        result = asyncio.run(
            runtime.tools.execute_tool("read_file", {"path": str(workspace_tmp)})
        )
        assert result["ok"] is True
        assert result["total_lines"] == 20
        assert result["total_bytes"] > 0
        assert result["encoding_used"] == "utf-8"
        assert result["truncated"] is False

        # Line-range read
        result2 = asyncio.run(
            runtime.tools.execute_tool(
                "read_file", {"path": str(workspace_tmp), "start_line": 5, "end_line": 8}
            )
        )
        assert result2["start_line"] == 5
        assert result2["end_line"] == 8
        content = result2["content"]
        assert "line 5" in content
        assert "line 8" in content
        assert "line 4" not in content
        assert "line 9" not in content
    finally:
        workspace_tmp.unlink(missing_ok=True)


def test_patch_file_tool_applies_unified_diff() -> None:
    runtime = build_runtime(Path(".").resolve())
    target = Path(".harness/test-phase2-patch.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    try:
        patch = (
            "--- a/target.txt\n"
            "+++ b/target.txt\n"
            "@@ -1,4 +1,4 @@\n"
            " alpha\n"
            "-beta\n"
            "+BETA\n"
            " gamma\n"
            " delta\n"
        )

        result = asyncio.run(
            runtime.tools.execute_tool(
                "patch_file", {"target_path": str(target), "patch": patch}
            )
        )

        assert result["ok"] is True
        assert result["hunks_applied"] == 1
        assert result["hunks_rejected"] == 0
        assert result["dry_run"] is False
        assert "BETA" in target.read_text(encoding="utf-8")
        assert "beta" not in target.read_text(encoding="utf-8")
        assert result["updated_paths"] != []
        assert result["patch_summary"].startswith("applied 1 hunk")
    finally:
        target.unlink(missing_ok=True)


def test_patch_file_tool_dry_run_does_not_write() -> None:
    runtime = build_runtime(Path(".").resolve())
    target = Path(".harness/test-phase2-patch-dry.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "hello\nworld\n"
    target.write_text(original, encoding="utf-8")
    try:
        patch = (
            "--- a/dry.txt\n"
            "+++ b/dry.txt\n"
            "@@ -1,2 +1,2 @@\n"
            "-hello\n"
            "+HELLO\n"
            " world\n"
        )

        result = asyncio.run(
            runtime.tools.execute_tool(
                "patch_file", {"target_path": str(target), "patch": patch, "dry_run": True}
            )
        )

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["hunks_applied"] == 1
        assert target.read_text(encoding="utf-8") == original  # unchanged
        assert result["updated_paths"] == []
        assert result["bytes_written"] == 0
    finally:
        target.unlink(missing_ok=True)


def test_install_dependencies_dry_run_returns_command() -> None:
    runtime = build_runtime(Path(".").resolve())

    result = asyncio.run(
        runtime.tools.execute_tool(
            "install_dependencies",
            {
                "package_manager": "pip",
                "packages": ["requests", "httpx"],
                "dry_run": True,
            },
        )
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["package_manager"] == "pip"
    assert "requests" in result["command"]
    assert "httpx" in result["command"]
    assert result["created_paths"] == []
    assert result["updated_paths"] == []


def test_install_dependencies_auto_detects_npm() -> None:
    runtime = build_runtime(Path(".").resolve())
    # frontend/ has package.json so npm should be auto-detected
    result = asyncio.run(
        runtime.tools.execute_tool(
            "install_dependencies",
            {
                "package_manager": "auto",
                "packages": ["is-odd"],
                "dry_run": True,
                "target_path": "frontend",
            },
        )
    )

    assert result["ok"] is True
    assert result["package_manager"] == "npm"
    assert "npm" in result["command"]


# ── Phase 3: Multi-File Context + Auto-Wire ───────────────────────────────────

def test_index_project_classifies_files() -> None:
    runtime = build_runtime(Path(".").resolve())
    result = asyncio.run(
        runtime.tools.execute_tool(
            "index_project",
            {"root_path": "."},
        )
    )
    assert result["ok"] is True
    assert result["total_files_indexed"] > 0
    by_kind = result["by_kind"]
    assert isinstance(by_kind, dict)
    # Workspace has Python modules and config files
    assert "module" in by_kind or "config" in by_kind
    # Index file should be produced
    index_path = Path(".harness") / "project_index.json"
    assert index_path.exists()
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    assert idx["total_files"] == result["total_files_indexed"]


def test_read_context_reads_explicit_paths() -> None:
    # Create a small test file for deterministic read
    test_file = Path(".harness") / "test-phase3-context.txt"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("hello context world\n", encoding="utf-8")

    runtime = build_runtime(Path(".").resolve())
    result = asyncio.run(
        runtime.tools.execute_tool(
            "read_context",
            {"paths": [".harness/test-phase3-context.txt"], "token_budget": 100},
        )
    )
    assert result["ok"] is True
    assert result["total_files_read"] == 1
    files = result["files"]
    assert len(files) == 1
    assert "hello context world" in files[0]["content"]
    assert len(result["provenance"]) == 1
    assert result["provenance"][0]["purpose"] == "context"


def test_read_context_respects_token_budget() -> None:
    # Write a file larger than a tiny budget to verify truncation
    test_file = Path(".harness") / "test-phase3-bigfile.txt"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    # 100 chars * 10 lines = 1000 chars > 10-token budget (40 chars)
    test_file.write_text("x" * 100 + "\n" * 10, encoding="utf-8")

    runtime = build_runtime(Path(".").resolve())
    result = asyncio.run(
        runtime.tools.execute_tool(
            "read_context",
            {"paths": [".harness/test-phase3-bigfile.txt"], "token_budget": 10},
        )
    )
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["total_tokens_estimate"] <= 10


def test_propose_wiring_vite_react_returns_proposals() -> None:
    runtime = build_runtime(Path(".").resolve())
    result = asyncio.run(
        runtime.tools.execute_tool(
            "propose_wiring",
            {
                "component_path": "frontend/src/views/Dashboard.tsx",
                "framework": "vite-react",
                "component_name": "Dashboard",
                "route_path": "/dashboard",
            },
        )
    )
    assert result["ok"] is True
    assert result["framework"] == "vite-react"
    assert result["component_name"] == "Dashboard"
    # Should include at least one proposal referencing App.tsx
    proposals = result["proposals"]
    assert isinstance(proposals, list)
    assert len(proposals) > 0
    assert any("App" in str(p.get("file", "")) or "router" in str(p.get("file", "")) for p in proposals)
    # Provenance should reference the component being wired
    provenance = result["provenance"]
    assert any(p["path"] == "frontend/src/views/Dashboard.tsx" for p in provenance)


def test_apply_wiring_dry_run_no_file_writes() -> None:
    # Create a minimal App.tsx with Routes block for the wiring engine to target
    app_tsx = Path(".harness") / "test-phase3-App.tsx"
    app_tsx.parent.mkdir(parents=True, exist_ok=True)
    app_tsx.write_text(
        "import React from 'react';\n\nfunction App() {\n  return (\n    <Routes>\n    </Routes>\n  );\n}\n",
        encoding="utf-8",
    )
    original = app_tsx.read_text(encoding="utf-8")

    runtime = build_runtime(Path(".").resolve())
    proposals = [
        {
            "file": ".harness/test-phase3-App.tsx",
            "patch_type": "insert_import_and_route",
            "component_name": "Dash",
            "import_line": "import { Dash } from './views/Dash';",
            "route_element": '<Route path="/dash" element={<Dash />} />',
        }
    ]
    result = asyncio.run(
        runtime.tools.execute_tool(
            "apply_wiring",
            {"proposals": proposals, "dry_run": True},
        )
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    # File must be unchanged
    assert app_tsx.read_text(encoding="utf-8") == original


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


def test_chat_can_create_task_template() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "prompt": "Create a weather widget app with html css and js",
            "create_task_template": True,
            "task_template_name": "Weather widget template",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["mode"] == "task-template"
    assert isinstance(body.get("task_template_id"), str)

    templates = client.get("/tasks/templates")
    assert templates.status_code == 200
    rows = templates.json()
    assert any(t.get("template_id") == body["task_template_id"] for t in rows)


def test_task_template_run_and_scheduler_binding() -> None:
    app = create_app(Path(".").resolve())
    client = TestClient(app)

    create_template = client.post(
        "/tasks/templates",
        json={
            "name": "quick local stub task",
            "prompt": "Say hello from template",
            "workflow_mode": "lightning",
            "model_backend": "local_stub",
        },
    )
    assert create_template.status_code == 200
    template_id = create_template.json()["template"]["template_id"]

    run_template = client.post(f"/tasks/templates/{template_id}/run", json={"model_backend": "local_stub"})
    assert run_template.status_code == 200
    run_body = run_template.json()
    assert run_body["ok"] is True
    assert isinstance(run_body["task_id"], str)

    bind_job = client.post(
        "/scheduler/template-jobs",
        json={
            "template_id": template_id,
            "job_id": "test-template-job",
            "schedule_type": "interval",
            "interval_seconds": 1,
            "enabled": True,
        },
    )
    assert bind_job.status_code == 200
    assert bind_job.json()["ok"] is True

    list_jobs = client.get("/scheduler/template-jobs")
    assert list_jobs.status_code == 200
    assert any(j.get("job_id") == "test-template-job" for j in list_jobs.json())

    tick = client.post("/scheduler/tick")
    assert tick.status_code == 200
    assert "test-template-job" in tick.json().get("ran_jobs", [])

    remove_job = client.delete("/scheduler/template-jobs/test-template-job")
    assert remove_job.status_code == 200
    assert remove_job.json()["deleted"] is True


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


def test_write_file_tool_writes_relative_workspace_path() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target = Path(".harness/test-write-file-tool.txt")
    target.unlink(missing_ok=True)

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "write_file",
                {
                    "target_path": ".harness/test-write-file-tool.txt",
                    "content": "hello from tool\n",
                },
            )
        )
        assert result["ok"] is True
        assert target.read_text(encoding="utf-8") == "hello from tool\n"
    finally:
        target.unlink(missing_ok=True)


def test_init_project_tool_creates_vite_react_scaffold() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-init-project-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Test Scaffold",
                    "target_path": ".harness/test-init-project-tool",
                },
            )
        )
        assert result["ok"] is True
        assert result["project_type"] == "vite-react"
        assert len(result["created_paths"]) >= 4
        assert target_dir.joinpath("package.json").exists()
        assert target_dir.joinpath("src", "App.jsx").exists()
        package_json = json.loads(target_dir.joinpath("package.json").read_text(encoding="utf-8"))
        assert package_json["name"] == "test-scaffold"
        assert "npm install" in result["commands_to_run"]
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_component_tool_creates_react_component() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-component-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Component Playground",
                    "target_path": ".harness/test-generate-component-tool",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_component",
                {
                    "framework": "vite-react",
                    "name": "hero banner",
                    "target_path": ".harness/test-generate-component-tool",
                    "props_schema": {"title": "string", "subtitle": "string"},
                },
            )
        )
        component_path = target_dir.joinpath("src", "components", "HeroBanner.jsx")
        assert result["ok"] is True
        assert component_path.exists()
        content = component_path.read_text(encoding="utf-8")
        assert "export function HeroBanner" in content
        assert "title" in content
        assert "subtitle" in content
        assert any(path.endswith("src/components/HeroBanner.jsx") for path in result["created_paths"])
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_camofox_same_prompt_enforces_requested_repo_tool_before_support_tools(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    runtime = app.state.runtime

    async def fake_camofox_handler(args: dict[str, object]) -> dict[str, object]:
        assert args.get("action") == "get_links"
        assert args.get("url") == "https://www.reddit.com/"
        return {
            "ok": True,
            "url": "https://www.reddit.com/",
            "links": [
                {
                    "url": "https://www.reddit.com/r/test/comments/123/example_post/",
                    "text": "Example post",
                }
            ],
            "evidence_snippet": "Example post",
        }

    runtime.tools.register_tool(
        ToolDefinition(
            name="repo_camofox-browser_http_request",
            description="Camoufox browser automation adapter",
            handler=fake_camofox_handler,
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["action", "url"],
            },
            capabilities=["browser.automation"],
        )
    )
    runtime.tools.policy.allowed_tool_names.add("repo_camofox-browser_http_request")

    class SequenceAdapter:
        model_id = "sequence"

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    text="",
                    model_id=self.model_id,
                    tool_calls=[ToolCall(id="1", name="list_directory", arguments={"path": "."})],
                )
            if self.calls == 2:
                return ModelResponse(
                    text="",
                    model_id=self.model_id,
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="repo_camofox_browser_http_request",
                            arguments={"action": "get_links", "url": "https://www.reddit.com/"},
                        )
                    ],
                )
            if self.calls == 3:
                return ModelResponse(
                    text="",
                    model_id=self.model_id,
                    tool_calls=[
                        ToolCall(
                            id="3",
                            name="append_file",
                            arguments={
                                "target_path": "reddit.txt",
                                "content": "https://www.reddit.com/r/test/comments/123/example_post/",
                            },
                        )
                    ],
                )
            if self.calls == 4:
                return ModelResponse(
                    text="",
                    model_id=self.model_id,
                    tool_calls=[ToolCall(id="4", name="read_file", arguments={"path": "reddit.txt"})],
                )
            return ModelResponse(
                text=(
                    "tools_used=[repo_camofox-browser_http_request, append_file, read_file]\n"
                    "https://www.reddit.com/r/test/comments/123/example_post/"
                ),
                model_id=self.model_id,
            )

        def estimate_tokens(self, text: str) -> int:
            return max(1, len(text) // 4)

    runtime.models.adapters["sequence"] = SequenceAdapter()

    result = asyncio.run(
        runtime.orchestrator.run_reactive_task(
            Task(
                id="camofox-prompt-regression",
                description=CAMOFOX_REDDIT_PROMPT,
                input={"model_backend": "sequence"},
            )
        )
    )

    assert result.success is True
    assert "repo_camofox-browser_http_request" in result.output["used_tools"]
    assert "list_directory" not in result.output["used_tools"]
    assert Path(tmp_path / "reddit.txt").read_text(encoding="utf-8").strip() == "https://www.reddit.com/r/test/comments/123/example_post/"


def test_generate_route_tool_creates_react_route_and_test() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-route-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Route Playground",
                    "target_path": ".harness/test-generate-route-tool",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_route",
                {
                    "framework": "vite-react",
                    "route_path": "/dashboard/overview",
                    "target_path": ".harness/test-generate-route-tool",
                    "with_loader": True,
                    "with_tests": True,
                },
            )
        )
        route_path = target_dir.joinpath("src", "routes", "DashboardOverviewRoute.jsx")
        test_path = target_dir.joinpath("src", "routes", "DashboardOverviewRoute.test.jsx")
        assert result["ok"] is True
        assert route_path.exists()
        assert test_path.exists()
        route_content = route_path.read_text(encoding="utf-8")
        assert "export async function loader()" in route_content
        assert "Route path: /dashboard/overview" in route_content
        assert any(path.endswith("src/routes/DashboardOverviewRoute.jsx") for path in result["created_paths"])
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_route_tool_creates_fastapi_route_and_test() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-fastapi-route-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "fastapi",
                    "name": "FastAPI Route Playground",
                    "target_path": ".harness/test-generate-fastapi-route-tool",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_route",
                {
                    "framework": "fastapi",
                    "route_path": "/health/check",
                    "target_path": ".harness/test-generate-fastapi-route-tool",
                    "with_tests": True,
                },
            )
        )
        route_path = target_dir.joinpath("app", "routes", "health_check.py")
        test_path = target_dir.joinpath("tests", "test_health_check_route.py")
        assert result["ok"] is True
        assert route_path.exists()
        assert test_path.exists()
        route_content = route_path.read_text(encoding="utf-8")
        assert "APIRouter" in route_content
        assert "prefix='/health/check'" in route_content
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_component_tool_creates_static_site_component() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-static-component-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "static-site",
                    "name": "Static Component Playground",
                    "target_path": ".harness/test-generate-static-component-tool",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_component",
                {
                    "framework": "static-site",
                    "name": "feature card",
                    "target_path": ".harness/test-generate-static-component-tool",
                },
            )
        )
        component_path = target_dir.joinpath("components", "feature-card.html")
        assert result["ok"] is True
        assert component_path.exists()
        content = component_path.read_text(encoding="utf-8")
        assert "component-feature-card" in content
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_route_tool_creates_static_site_route() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-static-route-tool")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "static-site",
                    "name": "Static Route Playground",
                    "target_path": ".harness/test-generate-static-route-tool",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_route",
                {
                    "framework": "static-site",
                    "route_path": "/docs/getting-started",
                    "target_path": ".harness/test-generate-static-route-tool",
                },
            )
        )
        route_path = target_dir.joinpath("routes", "docs-getting-started.html")
        assert result["ok"] is True
        assert route_path.exists()
        content = route_path.read_text(encoding="utf-8")
        assert "Route path: /docs/getting-started" in content
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_route_auto_wire_is_deferred() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-route-autowire")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Auto Wire Playground",
                    "target_path": ".harness/test-generate-route-autowire",
                },
            )
        )
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_route",
                {
                    "framework": "vite-react",
                    "route_path": "/auto-wire",
                    "target_path": ".harness/test-generate-route-autowire",
                    "auto_wire": True,
                },
            )
        )
        assert result["ok"] is True
        assert result["auto_wire_requested"] is True
        assert result["auto_wire_applied"] is False
        assert any("deferred" in str(note).lower() for note in result["notes"])
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_init_project_tool_can_run_dependency_install() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-init-project-install")
    captured_calls: list[tuple[str, tuple[str, ...], str | None]] = []

    async def fake_run_command(command: str, *args: str, timeout_s: int | None = None, cwd: str | None = None) -> ExecutionResult:
        captured_calls.append((command, args, cwd))
        return ExecutionResult(stdout="installed", stderr="", returncode=0, truncated=False)

    original_run_command = runtime.execution.run_command
    runtime.execution.run_command = fake_run_command  # type: ignore[assignment]

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Install Playground",
                    "target_path": ".harness/test-init-project-install",
                    "install_dependencies": True,
                },
            )
        )
        assert result["ok"] is True
        assert result["install_result"]["ok"] is True
        assert captured_calls
        assert captured_calls[0][0] == "npm"
        assert captured_calls[0][1] == ("install",)
    finally:
        runtime.execution.run_command = original_run_command  # type: ignore[assignment]
        shutil.rmtree(target_dir, ignore_errors=True)


def test_generate_component_is_idempotent_without_overwrite() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-generate-component-idempotent")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Idempotent Playground",
                    "target_path": ".harness/test-generate-component-idempotent",
                },
            )
        )
        asyncio.run(
            runtime.tools.execute_tool(
                "generate_component",
                {
                    "framework": "vite-react",
                    "name": "status badge",
                    "target_path": ".harness/test-generate-component-idempotent",
                },
            )
        )
        component_path = target_dir.joinpath("src", "components", "StatusBadge.jsx")
        original_content = component_path.read_text(encoding="utf-8")

        try:
            asyncio.run(
                runtime.tools.execute_tool(
                    "generate_component",
                    {
                        "framework": "vite-react",
                        "name": "status badge",
                        "target_path": ".harness/test-generate-component-idempotent",
                    },
                )
            )
            assert False, "Expected generate_component to fail when overwrite is false"
        except ValueError as exc:
            assert "overwrite=false" in str(exc)

        assert component_path.read_text(encoding="utf-8") == original_content
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_init_project_rolls_back_when_dependency_install_fails() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target_dir = Path(".harness/test-init-project-rollback")

    async def failing_run_command(command: str, *args: str, timeout_s: int | None = None, cwd: str | None = None) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr="install failed", returncode=1, truncated=False)

    original_run_command = runtime.execution.run_command
    runtime.execution.run_command = failing_run_command  # type: ignore[assignment]

    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "init_project",
                {
                    "project_type": "vite-react",
                    "name": "Rollback Playground",
                    "target_path": ".harness/test-init-project-rollback",
                    "install_dependencies": True,
                },
            )
        )
        assert result["ok"] is False
        assert result["rolled_back"] is True
        assert result["install_result"]["returncode"] == 1
        assert not target_dir.joinpath("package.json").exists()
        assert not target_dir.joinpath("src", "App.jsx").exists()
    finally:
        runtime.execution.run_command = original_run_command  # type: ignore[assignment]
        shutil.rmtree(target_dir, ignore_errors=True)


def test_version_bump_tool_updates_specified_files_only() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", pyproject)
    assert match is not None
    current_version = match.group(1)
    temp_file = Path(".harness/test-version-bump.txt")
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_text(f"version={current_version}\n", encoding="utf-8")

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "version_bump",
                {
                    "bump": "patch",
                    "files": [".harness/test-version-bump.txt"],
                },
            )
        )
        assert result["ok"] is True
        assert result["current_version"] == current_version
        assert temp_file.read_text(encoding="utf-8").strip() == f"version={result['next_version']}"
    finally:
        temp_file.unlink(missing_ok=True)


def test_version_bump_tool_dry_run_does_not_write_files() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", pyproject)
    assert match is not None
    current_version = match.group(1)
    temp_file = Path(".harness/test-version-bump-dry-run.txt")
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_text(f"version={current_version}\n", encoding="utf-8")

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "version_bump",
                {
                    "bump": "patch",
                    "files": [".harness/test-version-bump-dry-run.txt"],
                    "dry_run": True,
                },
            )
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["updated_files"] == []
        assert any(path.endswith("test-version-bump-dry-run.txt") for path in result["planned_files"])
        assert temp_file.read_text(encoding="utf-8").strip() == f"version={current_version}"
    finally:
        temp_file.unlink(missing_ok=True)


def test_generate_release_notes_tool_creates_file() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target = Path(".harness/RELEASE_NOTES_TEST.md")
    target.unlink(missing_ok=True)

    async def fake_git_log(command: str, *args: str, timeout_s: int | None = None, cwd: str | None = None) -> ExecutionResult:
        assert command == "git"
        assert args[:2] == ("log", "--oneline")
        stdout = "\n".join(
            [
                "abc1234 feat(ui): add dashboard shell",
                "def5678 fix(api): handle null payload",
                "f0f0f0f chore: update deps",
                "1122334 docs: refresh readme",
            ]
        )
        return ExecutionResult(stdout=stdout, stderr="", returncode=0, truncated=False)

    original_run_command = runtime.execution.run_command
    runtime.execution.run_command = fake_git_log  # type: ignore[assignment]

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_release_notes",
                {
                    "version": "9.9.9",
                    "output_path": ".harness/RELEASE_NOTES_TEST.md",
                    "max_commits": 5,
                },
            )
        )
        assert result["ok"] is True
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "Release Notes 9.9.9" in content
        assert "## Features" in content
        assert "feat(ui): add dashboard shell" in content
        assert "## Fixes" in content
        assert "fix(api): handle null payload" in content
        assert "## Chore" in content
        assert "chore: update deps" in content
    finally:
        runtime.execution.run_command = original_run_command  # type: ignore[assignment]
        target.unlink(missing_ok=True)


def test_generate_release_notes_tool_dry_run_does_not_create_file() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    target = Path(".harness/RELEASE_NOTES_DRY_RUN.md")
    target.unlink(missing_ok=True)

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "generate_release_notes",
                {
                    "version": "8.8.8",
                    "output_path": ".harness/RELEASE_NOTES_DRY_RUN.md",
                    "dry_run": True,
                },
            )
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["bytes_written"] == 0
        assert isinstance(result["content_preview"], str)
        assert not target.exists()
    finally:
        target.unlink(missing_ok=True)


def test_tag_and_publish_release_tool_uses_git_commands() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    called: list[tuple[str, tuple[str, ...]]] = []

    async def fake_git(command: str, *args: str, timeout_s: int | None = None, cwd: str | None = None) -> ExecutionResult:
        called.append((command, args))
        return ExecutionResult(stdout="ok", stderr="", returncode=0, truncated=False)

    original_run_command = runtime.execution.run_command
    runtime.execution.run_command = fake_git  # type: ignore[assignment]

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "tag_and_publish_release",
                {
                    "version": "1.2.3",
                    "push_main": True,
                },
            )
        )
        assert result["ok"] is True
        assert called[0] == ("git", ("tag", "v1.2.3"))
        assert called[1] == ("git", ("push", "origin", "v1.2.3"))
        assert called[2] == ("git", ("push", "origin", "main"))
    finally:
        runtime.execution.run_command = original_run_command  # type: ignore[assignment]


def test_tag_and_publish_release_tool_dry_run_skips_git_calls() -> None:
    app = create_app(Path(".").resolve())
    runtime = app.state.runtime
    called: list[tuple[str, tuple[str, ...]]] = []

    async def fake_git(command: str, *args: str, timeout_s: int | None = None, cwd: str | None = None) -> ExecutionResult:
        called.append((command, args))
        return ExecutionResult(stdout="ok", stderr="", returncode=0, truncated=False)

    original_run_command = runtime.execution.run_command
    runtime.execution.run_command = fake_git  # type: ignore[assignment]

    try:
        result = asyncio.run(
            runtime.tools.execute_tool(
                "tag_and_publish_release",
                {
                    "version": "2.3.4",
                    "push_main": True,
                    "dry_run": True,
                },
            )
        )
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert called == []
        assert "git tag v2.3.4" in result["planned_commands"][0]
        assert "git push origin v2.3.4" in result["planned_commands"][1]
        assert "git push origin main" in result["planned_commands"][2]
    finally:
        runtime.execution.run_command = original_run_command  # type: ignore[assignment]


def test_lightning_skill_prompt_hides_builtin_workflow_skills() -> None:
    app = create_app(Path(".").resolve())
    skills_section = app.state.runtime.skills.format_for_system_prompt("lightning")
    assert "brainstorming" not in skills_section
    assert "subagent-driven-development" not in skills_section


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
    runtime.tools.policy.deny_all_by_default = True
    blocked = client.post(
        f"/agents/{agent_id}/skills/safe_shell_command/execute",
        json={"input": {"command": "python --version"}},
    )
    assert blocked.status_code == 403
    runtime.tools.policy.deny_all_by_default = False

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
    assert any(row["skill_id"] == "brainstorming" for row in body)
    assert any(row["skill_id"] == "writing-plans" for row in body)
    assert any(row["skill_id"] == "subagent-driven-development" for row in body)
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
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_spec_approval", True)
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_plan_approval", True)
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
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_spec_approval", True)
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_plan_approval", True)
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_task_reviews", True)
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
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_spec_approval", True)
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_plan_approval", True)
    app.state.runtime.config.set("orchestrator.superpowered_mode.require_task_reviews", True)
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


def test_chat_lightning_triggers_subagents_and_returns_response() -> None:
    app = create_app(Path(".").resolve())
    app.state.runtime.config.set("orchestrator.enable_subagents", True)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "prompt": (
                "Research current weather patterns in Brooklyn and then draft an implementation plan "
                "for a weather widget API, including a short testing checklist."
            ),
            "model_backend": "local_stub",
            "workflow_mode": "lightning",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["workflow_mode"] == "lightning"
    assert isinstance(body["response"], str) and body["response"].strip()

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    task_id = tasks.json()[0]["task_id"]

    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    output = detail.json()["output"]
    spawned = output.get("spawned_subagents", [])
    assert output.get("workflow_mode") == "lightning"
    assert isinstance(spawned, list)
    assert 1 <= len(spawned) <= 3

    agents = client.get("/agents")
    assert agents.status_code == 200
    known_agent_ids = {row["agent_id"] for row in agents.json()}
    for spawned_id in spawned:
        assert spawned_id in known_agent_ids


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


def test_lmstudio_adapter_parses_curly_brace_tool_call_syntax() -> None:
    """Model sometimes emits {args} instead of (args) — must be handled."""
    adapter = LMStudioAdapter(
        base_url="http://127.0.0.1:1234/v1",
        default_model="test-model",
    )

    parsed = adapter._extract_pseudo_tool_calls(
        '<|tool_call|>call:web_fetch{url: "https://wttr.in/Brooklyn?format=3"}<tool_call>'
    )

    assert len(parsed) == 1
    assert parsed[0].name == "web_fetch"
    assert parsed[0].arguments.get("url") == "https://wttr.in/Brooklyn?format=3"


def test_lmstudio_adapter_parses_malformed_delimiter_and_whitespace_tool_call() -> None:
    adapter = LMStudioAdapter(
        base_url="http://127.0.0.1:1234/v1",
        default_model="test-model",
    )

    parsed = adapter._extract_pseudo_tool_calls(
        '<|tool_call>call:subagent-driven-development {"plan": "draft widget app"}<tool_call|>'
    )

    assert len(parsed) == 1
    assert parsed[0].name == "subagent-driven-development"
    assert parsed[0].arguments == {"plan": "draft widget app"}

