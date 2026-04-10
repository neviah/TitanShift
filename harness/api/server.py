from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from harness.api.schemas import (
    AgentSummary,
    ChatRequest,
    ChatResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    LogEntry,
    RunHistoryExportRequest,
    RunHistoryExportResponse,
    RunHistoryPolicy,
    RunHistoryReport,
    SchedulerJobToggleRequest,
    SchedulerJobToggleResponse,
    SchedulerHeartbeatResponse,
    SchedulerJob,
    SchedulerTickResponse,
    MemoryGraphNeighbors,
    MemorySemanticHit,
    MemorySummary,
    SkillSummary,
    TaskDetail,
    TaskSummary,
    ToolSummary,
)
from harness.runtime.bootstrap import RuntimeContext, build_runtime
from harness.runtime.types import Task


def create_app(workspace_root: Path) -> FastAPI:
    runtime: RuntimeContext = build_runtime(workspace_root)
    app = FastAPI(title="TitantShift Harness API", version="0.1.0")
    app.state.runtime = runtime

    async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        enabled = bool(runtime.config.get("api.require_api_key", False))
        if not enabled:
            return
        expected = str(runtime.config.get("api.api_key", "")).strip()
        if not expected:
            raise HTTPException(status_code=500, detail="API key auth enabled but no api.api_key configured")
        if x_api_key != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _report_redacted_keys() -> list[str]:
        keys = runtime.config.get("reports.redacted_keys", [])
        if isinstance(keys, list):
            return [str(k).lower() for k in keys]
        return []

    def _is_redacted_key(key: str, redacted_keys: set[str]) -> bool:
        k = key.lower()
        return any(candidate in k for candidate in redacted_keys)

    def _redact_value(value: Any, redacted_keys: set[str]) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for k, v in value.items():
                if _is_redacted_key(str(k), redacted_keys):
                    redacted[str(k)] = "***REDACTED***"
                else:
                    redacted[str(k)] = _redact_value(v, redacted_keys)
            return redacted
        if isinstance(value, list):
            return [_redact_value(v, redacted_keys) for v in value]
        return value

    def _build_run_history_report(task_limit: int, log_limit: int, redact: bool | None) -> RunHistoryReport:
        clamped_task_limit = max(1, min(task_limit, 100))
        clamped_log_limit = max(1, min(log_limit, 500))
        apply_redaction = bool(runtime.config.get("reports.redact_by_default", True)) if redact is None else redact
        redacted_keys = set(_report_redacted_keys())

        all_tasks = runtime.orchestrator.list_tasks()
        recent_tasks_raw = all_tasks[:clamped_task_limit]
        recent_events_raw = runtime.logger.query(limit=clamped_log_limit)

        if apply_redaction and redacted_keys:
            recent_events_raw = [
                {
                    "timestamp": e.get("timestamp"),
                    "event_type": e.get("event_type"),
                    "payload": _redact_value(e.get("payload", {}), redacted_keys),
                }
                for e in recent_events_raw
            ]

        failed_tasks = sum(1 for t in all_tasks if t.get("status") == "failed")
        loaded_modules = runtime.module_loader.list_modules()
        generated_at = datetime.now(timezone.utc)
        config_snapshot = {
            "model.default_backend": runtime.config.get("model.default_backend"),
            "orchestrator.enable_subagents": runtime.config.get("orchestrator.enable_subagents"),
            "tools.deny_all_by_default": runtime.config.get("tools.deny_all_by_default"),
            "reports.redact_by_default": bool(runtime.config.get("reports.redact_by_default", True)),
            "reports.redacted_keys": _report_redacted_keys(),
        }
        signing_version = "v1"
        signature_payload = {
            "generated_at": generated_at.isoformat(),
            "signing_version": signing_version,
            "redaction_applied": apply_redaction,
            "total_tasks": len(all_tasks),
            "failed_tasks": failed_tasks,
            "recent_tasks": recent_tasks_raw,
            "recent_events": recent_events_raw,
            "health": runtime.health.as_list(),
            "loaded_modules": loaded_modules,
            "config_snapshot": config_snapshot,
        }
        digest = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        report_hash = f"sha256:{digest}"

        return RunHistoryReport(
            generated_at=generated_at,
            signing_version=signing_version,
            report_hash=report_hash,
            redaction_applied=apply_redaction,
            total_tasks=len(all_tasks),
            failed_tasks=failed_tasks,
            recent_tasks=[TaskSummary(**t) for t in recent_tasks_raw],
            recent_events=[LogEntry(**e) for e in recent_events_raw],
            health=runtime.health.as_list(),
            loaded_modules=loaded_modules,
            config_snapshot=config_snapshot,
        )

    @app.get("/status", dependencies=[Depends(require_api_key)])
    async def status() -> dict:
        return {
            "ok": True,
            "subagents_enabled": runtime.config.get("orchestrator.enable_subagents"),
            "graph_backend": runtime.config.get("memory.graph_backend"),
            "semantic_backend": runtime.config.get("memory.semantic_backend"),
            "default_model_backend": runtime.config.get("model.default_backend"),
            "health": runtime.health.as_list(),
        }

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
    async def chat(body: ChatRequest) -> ChatResponse:
        task_input: dict = {}
        if body.model_backend:
            task_input["model_backend"] = body.model_backend
        if body.budget:
            task_input["budget"] = body.budget.model_dump(exclude_none=True)

        task = Task(
            id=str(uuid.uuid4()),
            description=body.prompt,
            input=task_input,
        )
        result = await runtime.orchestrator.run_reactive_task(task)
        return ChatResponse(
            success=result.success,
            response=result.output.get("response", ""),
            model=result.output.get("model", "unknown"),
            mode=result.output.get("mode", "reactive"),
            error=result.error,
            estimated_total_tokens=result.output.get("estimated_total_tokens"),
        )

    @app.get("/tasks", response_model=list[TaskSummary], dependencies=[Depends(require_api_key)])
    async def list_tasks() -> list[TaskSummary]:
        return [TaskSummary(**t) for t in runtime.orchestrator.list_tasks()]

    @app.get("/tasks/{task_id}", response_model=TaskDetail, dependencies=[Depends(require_api_key)])
    async def get_task(task_id: str) -> TaskDetail:
        task = runtime.orchestrator.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskDetail(**task)

    @app.get("/logs", response_model=list[LogEntry], dependencies=[Depends(require_api_key)])
    async def get_logs(
        event_type: str | None = None,
        task_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[LogEntry]:
        clamped_limit = max(1, min(limit, 1000))
        rows = runtime.logger.query(
            event_type=event_type,
            task_id=task_id,
            source=source,
            limit=clamped_limit,
        )
        return [LogEntry(**r) for r in rows]

    @app.get("/config", dependencies=[Depends(require_api_key)])
    async def get_config() -> dict:
        return {
            "model.default_backend": runtime.config.get("model.default_backend"),
            "orchestrator.enable_subagents": runtime.config.get("orchestrator.enable_subagents"),
            "state_machine.default_budget.max_steps": runtime.config.get("state_machine.default_budget.max_steps"),
            "state_machine.default_budget.max_tokens": runtime.config.get("state_machine.default_budget.max_tokens"),
            "state_machine.default_budget.max_duration_ms": runtime.config.get(
                "state_machine.default_budget.max_duration_ms"
            ),
            "tools.deny_all_by_default": runtime.config.get("tools.deny_all_by_default"),
            "tools.allow_network": runtime.config.get("tools.allow_network"),
        }

    @app.post("/config", response_model=ConfigUpdateResponse, dependencies=[Depends(require_api_key)])
    async def update_config(body: ConfigUpdateRequest) -> ConfigUpdateResponse:
        runtime.config.set(body.key, body.value)
        runtime.logger.log("CONFIG_UPDATED", {"key": body.key})
        return ConfigUpdateResponse(ok=True, key=body.key, value=runtime.config.get(body.key))

    @app.get("/scheduler/jobs", response_model=list[SchedulerJob], dependencies=[Depends(require_api_key)])
    async def scheduler_jobs() -> list[SchedulerJob]:
        return [SchedulerJob(**j) for j in runtime.scheduler.list_jobs()]

    @app.get("/agents", response_model=list[AgentSummary], dependencies=[Depends(require_api_key)])
    async def agents() -> list[AgentSummary]:
        return [
            AgentSummary(
                agent_id="main-agent",
                role=runtime.config.get("orchestrator.default_role", "General Agent"),
                subagents_enabled=runtime.config.get("orchestrator.enable_subagents", False),
                model_default_backend=runtime.config.get("model.default_backend", "local_stub"),
                memory_layers=["working", "short_term", "long_term", "semantic", "graph"],
            )
        ]

    @app.get("/skills", response_model=list[SkillSummary], dependencies=[Depends(require_api_key)])
    async def skills(query: str | None = None) -> list[SkillSummary]:
        rows = runtime.skills.search_skills(query) if query else runtime.skills.list_skills()
        return [
            SkillSummary(
                skill_id=s.skill_id,
                description=s.description,
                tags=list(s.tags),
                required_tools=list(s.required_tools),
            )
            for s in rows
        ]

    @app.get("/tools", response_model=list[ToolSummary], dependencies=[Depends(require_api_key)])
    async def tools(query: str | None = None) -> list[ToolSummary]:
        rows = runtime.tools.search_tools(query) if query else runtime.tools.list_tools()
        out: list[ToolSummary] = []
        for t in rows:
            allowed, reason = runtime.tools.preview_policy(t)
            out.append(
                ToolSummary(
                    name=t.name,
                    description=t.description,
                    needs_network=t.needs_network,
                    required_paths=list(t.required_paths),
                    required_commands=list(t.required_commands),
                    allowed_by_policy=allowed,
                    policy_reason=reason,
                )
            )
        return out

    @app.post("/scheduler/heartbeat", response_model=SchedulerHeartbeatResponse, dependencies=[Depends(require_api_key)])
    async def scheduler_heartbeat() -> SchedulerHeartbeatResponse:
        runtime.logger.log("SCHEDULER_HEARTBEAT", {"source": "api"})
        hb = runtime.scheduler.heartbeat()
        return SchedulerHeartbeatResponse(**hb)

    @app.post("/scheduler/tick", response_model=SchedulerTickResponse, dependencies=[Depends(require_api_key)])
    async def scheduler_tick() -> SchedulerTickResponse:
        result = await runtime.scheduler.tick()
        runtime.logger.log("SCHEDULER_TICK", result)
        return SchedulerTickResponse(**result)

    @app.post(
        "/scheduler/jobs/{job_id}/enabled",
        response_model=SchedulerJobToggleResponse,
        dependencies=[Depends(require_api_key)],
    )
    async def scheduler_job_enabled(job_id: str, body: SchedulerJobToggleRequest) -> SchedulerJobToggleResponse:
        job = runtime.scheduler.set_enabled(job_id, body.enabled)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        runtime.logger.log("SCHEDULER_JOB_TOGGLED", {"job_id": job_id, "enabled": body.enabled, "source": "api"})
        return SchedulerJobToggleResponse(job_id=job_id, enabled=job.enabled)

    @app.get("/memory/summary", response_model=MemorySummary, dependencies=[Depends(require_api_key)])
    async def memory_summary() -> MemorySummary:
        return MemorySummary(**runtime.memory.summary())

    @app.get("/memory/semantic-search", response_model=list[MemorySemanticHit], dependencies=[Depends(require_api_key)])
    async def memory_semantic_search(query: str, limit: int = 5) -> list[MemorySemanticHit]:
        clamped_limit = max(1, min(limit, 100))
        rows = runtime.memory.semantic_search(query=query, limit=clamped_limit)
        return [MemorySemanticHit(**r) for r in rows]

    @app.get("/memory/graph/neighbors", response_model=MemoryGraphNeighbors, dependencies=[Depends(require_api_key)])
    async def memory_graph_neighbors(node_id: str) -> MemoryGraphNeighbors:
        neighbors = runtime.memory.graph_neighbors(node_id)
        return MemoryGraphNeighbors(node_id=node_id, neighbors=neighbors)

    @app.get("/reports/run-history", response_model=RunHistoryReport, dependencies=[Depends(require_api_key)])
    async def run_history_report(task_limit: int = 10, log_limit: int = 50, redact: bool | None = None) -> RunHistoryReport:
        return _build_run_history_report(task_limit=task_limit, log_limit=log_limit, redact=redact)

    @app.post("/reports/run-history/export", response_model=RunHistoryExportResponse, dependencies=[Depends(require_api_key)])
    async def run_history_export(body: RunHistoryExportRequest) -> RunHistoryExportResponse:
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Export path blocked by execution policy")

        report = _build_run_history_report(task_limit=body.task_limit, log_limit=body.log_limit, redact=body.redact)
        payload = report.model_dump(mode="json")
        text = json.dumps(payload, indent=2, sort_keys=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")

        runtime.logger.log(
            "REPORT_EXPORTED",
            {"path": str(target), "report_hash": report.report_hash, "source": "api"},
        )

        return RunHistoryExportResponse(
            ok=True,
            path=str(target),
            bytes_written=target.stat().st_size,
            report_hash=report.report_hash,
        )

    @app.get("/reports/policy", response_model=RunHistoryPolicy, dependencies=[Depends(require_api_key)])
    async def report_policy() -> RunHistoryPolicy:
        return RunHistoryPolicy(
            redact_by_default=bool(runtime.config.get("reports.redact_by_default", True)),
            redacted_keys=_report_redacted_keys(),
        )

    return app
