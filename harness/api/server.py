from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from harness.api.schemas import (
    AgentAssignSkillsRequest,
    AgentAssignSkillsResponse,
    AgentSkillExecuteRequest,
    AgentSkillExecuteResponse,
    AgentSpawnRequest,
    AgentSpawnResponse,
    AgentSummary,
    ArtifactCleanupRequest,
    ArtifactCleanupResponse,
    ChatRequest,
    ChatResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    LogEntry,
    RunHistoryExportRequest,
    RunHistoryExportResponse,
    RunHistoryPolicy,
    RunHistoryReport,
    RunHistoryVerifyRequest,
    RunHistoryVerifyResponse,
    SchedulerJobToggleRequest,
    SchedulerJobToggleResponse,
    SchedulerHeartbeatResponse,
    SchedulerJob,
    SchedulerTickResponse,
    MemoryGraphNeighbors,
    MemoryGraphNodeHit,
    MemorySemanticHit,
    MemorySummary,
    SkillExecuteRequest,
    SkillExecuteResponse,
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

    def _validate_api_key(*, supplied: str | None, expected: str, enabled: bool, missing_detail: str) -> None:
        if not enabled:
            return
        if not expected:
            raise HTTPException(status_code=500, detail=missing_detail)
        if supplied != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")

    async def require_read_api_key(x_api_key: str | None = Header(default=None)) -> None:
        _validate_api_key(
            supplied=x_api_key,
            expected=str(runtime.config.get("api.api_key", "")).strip(),
            enabled=bool(runtime.config.get("api.require_api_key", False)),
            missing_detail="API key auth enabled but no api.api_key configured",
        )

    async def require_admin_api_key(x_api_key: str | None = Header(default=None)) -> None:
        admin_enabled = bool(runtime.config.get("api.require_admin_api_key", False))
        if admin_enabled:
            _validate_api_key(
                supplied=x_api_key,
                expected=str(runtime.config.get("api.admin_api_key", "")).strip(),
                enabled=True,
                missing_detail="Admin API key auth enabled but no api.admin_api_key configured",
            )
            return
        await require_read_api_key(x_api_key)

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

    def _compute_report_hash_from_payload(payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"sha256:{digest}"

    def _signature_payload_from_report(report_data: dict[str, Any]) -> dict[str, Any]:
        generated_at = report_data.get("generated_at")
        if isinstance(generated_at, str) and generated_at.endswith("Z"):
            generated_at = generated_at[:-1] + "+00:00"
        return {
            "generated_at": generated_at,
            "signing_version": report_data.get("signing_version"),
            "redaction_applied": report_data.get("redaction_applied"),
            "total_tasks": report_data.get("total_tasks"),
            "failed_tasks": report_data.get("failed_tasks"),
            "recent_tasks": report_data.get("recent_tasks"),
            "recent_events": report_data.get("recent_events"),
            "health": report_data.get("health"),
            "loaded_modules": report_data.get("loaded_modules"),
            "config_snapshot": report_data.get("config_snapshot"),
        }

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
        recent_tasks = [TaskSummary(**t) for t in recent_tasks_raw]
        recent_events = [LogEntry(**e) for e in recent_events_raw]
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
            "recent_tasks": [r.model_dump(mode="json") for r in recent_tasks],
            "recent_events": [r.model_dump(mode="json") for r in recent_events],
            "health": runtime.health.as_list(),
            "loaded_modules": loaded_modules,
            "config_snapshot": config_snapshot,
        }
        report_hash = _compute_report_hash_from_payload(signature_payload)

        return RunHistoryReport(
            generated_at=generated_at,
            signing_version=signing_version,
            report_hash=report_hash,
            redaction_applied=apply_redaction,
            total_tasks=len(all_tasks),
            failed_tasks=failed_tasks,
            recent_tasks=recent_tasks,
            recent_events=recent_events,
            health=runtime.health.as_list(),
            loaded_modules=loaded_modules,
            config_snapshot=config_snapshot,
        )

    def _storage_root() -> Path:
        return runtime.logger.log_file.parent.resolve()

    def _candidate_cleanup_paths(include_logs: bool) -> list[Path]:
        root = _storage_root()
        report_glob = str(runtime.config.get("reports.cleanup_glob", "*.json"))
        candidates = [path for path in root.glob(report_glob) if path.is_file()]
        if include_logs and runtime.logger.log_file.exists():
            candidates.append(runtime.logger.log_file.resolve())
        deduped: dict[str, Path] = {str(path.resolve()): path.resolve() for path in candidates}
        return list(deduped.values())

    def _cleanup_artifacts(max_age_days: int, include_logs: bool, dry_run: bool) -> tuple[list[str], list[str]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        deleted_paths: list[str] = []
        skipped_paths: list[str] = []
        for path in _candidate_cleanup_paths(include_logs=include_logs):
            if not runtime.execution.policy.is_cwd_allowed(path.parent):
                skipped_paths.append(str(path))
                continue
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified_at > cutoff:
                skipped_paths.append(str(path))
                continue
            if dry_run:
                deleted_paths.append(str(path))
                continue
            try:
                os.remove(path)
                deleted_paths.append(str(path))
            except OSError:
                skipped_paths.append(str(path))
        return deleted_paths, skipped_paths

    @app.get("/status", dependencies=[Depends(require_read_api_key)])
    async def status() -> dict:
        return {
            "ok": True,
            "subagents_enabled": runtime.config.get("orchestrator.enable_subagents"),
            "graph_backend": runtime.config.get("memory.graph_backend"),
            "semantic_backend": runtime.config.get("memory.semantic_backend"),
            "default_model_backend": runtime.config.get("model.default_backend"),
            "health": runtime.health.as_list(),
        }

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_read_api_key)])
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

    @app.get("/tasks", response_model=list[TaskSummary], dependencies=[Depends(require_read_api_key)])
    async def list_tasks() -> list[TaskSummary]:
        return [TaskSummary(**t) for t in runtime.orchestrator.list_tasks()]

    @app.get("/tasks/{task_id}", response_model=TaskDetail, dependencies=[Depends(require_read_api_key)])
    async def get_task(task_id: str) -> TaskDetail:
        task = runtime.orchestrator.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskDetail(**task)

    @app.get("/logs", response_model=list[LogEntry], dependencies=[Depends(require_read_api_key)])
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

    @app.get("/config", dependencies=[Depends(require_read_api_key)])
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

    @app.post("/config", response_model=ConfigUpdateResponse, dependencies=[Depends(require_admin_api_key)])
    async def update_config(body: ConfigUpdateRequest) -> ConfigUpdateResponse:
        runtime.config.set(body.key, body.value)
        runtime.logger.log("CONFIG_UPDATED", {"key": body.key})
        return ConfigUpdateResponse(ok=True, key=body.key, value=runtime.config.get(body.key))

    @app.get("/scheduler/jobs", response_model=list[SchedulerJob], dependencies=[Depends(require_read_api_key)])
    async def scheduler_jobs() -> list[SchedulerJob]:
        return [SchedulerJob(**j) for j in runtime.scheduler.list_jobs()]

    @app.get("/agents", response_model=list[AgentSummary], dependencies=[Depends(require_read_api_key)])
    async def agents() -> list[AgentSummary]:
        subagents_enabled = bool(runtime.config.get("orchestrator.enable_subagents", False))
        model_default_backend = str(runtime.config.get("model.default_backend", "local_stub"))
        rows = []
        for agent in runtime.orchestrator.list_agents():
            rows.append(
                AgentSummary(
                    agent_id=agent["agent_id"],
                    role=agent["role"],
                    subagents_enabled=subagents_enabled,
                    model_default_backend=model_default_backend,
                    memory_layers=["working", "short_term", "long_term", "semantic", "graph"],
                    assigned_skills=list(agent.get("assigned_skills", [])),
                    allowed_tools=list(agent.get("allowed_tools", [])),
                    spawned_from_task=agent.get("spawned_from_task"),
                    created_at=agent.get("created_at"),
                    active=bool(agent.get("active", True)),
                )
            )
        return rows

    @app.post("/agents/spawn", response_model=AgentSpawnResponse, dependencies=[Depends(require_admin_api_key)])
    async def spawn_agent(body: AgentSpawnRequest) -> AgentSpawnResponse:
        task = Task(
            id=f"spawn-{uuid.uuid4()}",
            description=body.description,
            input={
                "role": body.role or "Specialist Agent",
                "model_backend": body.model_backend or runtime.config.get("model.default_backend", "local_stub"),
            },
        )
        try:
            agent_id = await runtime.orchestrator.spawn_subagent(task)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        agent = next((a for a in runtime.orchestrator.list_agents() if a.get("agent_id") == agent_id), None)
        return AgentSpawnResponse(
            ok=True,
            agent_id=agent_id,
            assigned_skills=list(agent.get("assigned_skills", [])) if agent else [],
            allowed_tools=list(agent.get("allowed_tools", [])) if agent else [],
        )

    @app.post(
        "/agents/{agent_id}/skills/assign",
        response_model=AgentAssignSkillsResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def assign_agent_skills(agent_id: str, body: AgentAssignSkillsRequest) -> AgentAssignSkillsResponse:
        try:
            agent = await runtime.orchestrator.assign_skills_to_agent(agent_id, body.skill_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return AgentAssignSkillsResponse(
            ok=True,
            agent_id=agent.agent_id,
            assigned_skills=list(agent.assigned_skills),
            allowed_tools=list(agent.allowed_tools),
        )

    @app.get("/skills", response_model=list[SkillSummary], dependencies=[Depends(require_read_api_key)])
    async def skills(
        query: str | None = None,
        tags: str | None = None,
        related_node_id: str | None = None,
    ) -> list[SkillSummary]:
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        if query:
            rows = runtime.skills.search_skills(query, tags=tag_list)
        elif tag_list:
            rows = runtime.skills.search_skills("", tags=tag_list)
        else:
            rows = runtime.skills.list_skills()

        if related_node_id:
            neighbors = set(runtime.memory.graph_neighbors(related_node_id))
            allowed_skill_ids = {n.removeprefix("skill:") for n in neighbors if n.startswith("skill:")}
            rows = [s for s in rows if s.skill_id in allowed_skill_ids]

        related_tools: set[str] = set()
        if related_node_id:
            if related_node_id.startswith("tool:"):
                related_tools.add(related_node_id.removeprefix("tool:"))
            for n in runtime.memory.graph_neighbors(related_node_id):
                if n.startswith("tool:"):
                    related_tools.add(n.removeprefix("tool:"))

        normalized_tags = {t.lower() for t in tag_list}
        ranked_rows: list[tuple[float, Any]] = []
        for s in rows:
            query_score = 0.0
            if query:
                q = query.lower()
                if q in s.skill_id.lower():
                    query_score += 2.0
                if q in s.description.lower():
                    query_score += 1.5
                if any(q in tag.lower() for tag in s.tags):
                    query_score += 1.0

            tag_overlap = len({t.lower() for t in s.tags}.intersection(normalized_tags))
            tool_overlap = len(set(s.required_tools).intersection(related_tools))
            score = query_score + float(tag_overlap * 2) + float(tool_overlap * 3)
            ranked_rows.append((score, s))

        ranked_rows.sort(key=lambda item: (-item[0], item[1].skill_id))

        return [
            SkillSummary(
                skill_id=s.skill_id,
                description=s.description,
                mode=s.mode,
                domain=s.domain,
                version=s.version,
                tags=list(s.tags),
                required_tools=list(s.required_tools),
                ranking_score=score,
            )
            for score, s in ranked_rows
        ]

    @app.post(
        "/skills/{skill_id}/execute",
        response_model=SkillExecuteResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def execute_skill(skill_id: str, body: SkillExecuteRequest) -> SkillExecuteResponse:
        try:
            result = await runtime.orchestrator.execute_skill(skill_id, body.input)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return SkillExecuteResponse(ok=bool(result.get("ok", False)), skill_id=skill_id, result=result)

    @app.post(
        "/agents/{agent_id}/skills/{skill_id}/execute",
        response_model=AgentSkillExecuteResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def execute_agent_skill(agent_id: str, skill_id: str, body: AgentSkillExecuteRequest) -> AgentSkillExecuteResponse:
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        try:
            result = await runtime.orchestrator.execute_skill_as_agent(agent_id, skill_id, body.input)
            runtime.logger.log(
                "AGENT_SKILL_EXECUTED",
                {
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "ok": bool(result.get("ok", False)),
                    "source": "api",
                },
            )
            return AgentSkillExecuteResponse(
                ok=bool(result.get("ok", False)),
                execution_id=execution_id,
                agent_id=agent_id,
                skill_id=skill_id,
                result=result,
            )
        except KeyError as exc:
            runtime.logger.log(
                "AGENT_SKILL_EXECUTED",
                {
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "ok": False,
                    "error": str(exc),
                    "source": "api",
                },
            )
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            runtime.logger.log(
                "AGENT_SKILL_EXECUTED",
                {
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "ok": False,
                    "error": str(exc),
                    "source": "api",
                },
            )
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except TimeoutError as exc:
            runtime.logger.log(
                "AGENT_SKILL_EXECUTED",
                {
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "ok": False,
                    "error": str(exc),
                    "source": "api",
                },
            )
            raise HTTPException(status_code=504, detail=str(exc)) from exc

    @app.get("/tools", response_model=list[ToolSummary], dependencies=[Depends(require_read_api_key)])
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

    @app.post("/scheduler/heartbeat", response_model=SchedulerHeartbeatResponse, dependencies=[Depends(require_admin_api_key)])
    async def scheduler_heartbeat() -> SchedulerHeartbeatResponse:
        runtime.logger.log("SCHEDULER_HEARTBEAT", {"source": "api"})
        hb = runtime.scheduler.heartbeat()
        return SchedulerHeartbeatResponse(**hb)

    @app.post("/scheduler/tick", response_model=SchedulerTickResponse, dependencies=[Depends(require_admin_api_key)])
    async def scheduler_tick() -> SchedulerTickResponse:
        result = await runtime.scheduler.tick()
        runtime.logger.log("SCHEDULER_TICK", result)
        return SchedulerTickResponse(**result)

    @app.post(
        "/scheduler/jobs/{job_id}/enabled",
        response_model=SchedulerJobToggleResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def scheduler_job_enabled(job_id: str, body: SchedulerJobToggleRequest) -> SchedulerJobToggleResponse:
        job = runtime.scheduler.set_enabled(job_id, body.enabled)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        runtime.logger.log("SCHEDULER_JOB_TOGGLED", {"job_id": job_id, "enabled": body.enabled, "source": "api"})
        return SchedulerJobToggleResponse(job_id=job_id, enabled=job.enabled)

    @app.get("/memory/summary", response_model=MemorySummary, dependencies=[Depends(require_read_api_key)])
    async def memory_summary() -> MemorySummary:
        return MemorySummary(**runtime.memory.summary())

    @app.get("/memory/semantic-search", response_model=list[MemorySemanticHit], dependencies=[Depends(require_read_api_key)])
    async def memory_semantic_search(query: str, limit: int = 5) -> list[MemorySemanticHit]:
        clamped_limit = max(1, min(limit, 100))
        rows = runtime.memory.semantic_search(query=query, limit=clamped_limit)
        return [MemorySemanticHit(**r) for r in rows]

    @app.get("/memory/graph/neighbors", response_model=MemoryGraphNeighbors, dependencies=[Depends(require_read_api_key)])
    async def memory_graph_neighbors(node_id: str) -> MemoryGraphNeighbors:
        neighbors = runtime.memory.graph_neighbors(node_id)
        return MemoryGraphNeighbors(node_id=node_id, neighbors=neighbors)

    @app.get("/memory/graph/search", response_model=list[MemoryGraphNodeHit], dependencies=[Depends(require_read_api_key)])
    async def memory_graph_search(
        query: str,
        node_type: str | None = None,
        limit: int = 20,
    ) -> list[MemoryGraphNodeHit]:
        clamped_limit = max(1, min(limit, 100))
        rows = runtime.memory.graph_search_nodes(query=query, node_type=node_type, limit=clamped_limit)
        return [
            MemoryGraphNodeHit(
                node_id=str(r.get("node_id", "")),
                node_type=str(r.get("node_type", "")),
                properties={k: str(v) for k, v in dict(r.get("properties", {})).items()},
            )
            for r in rows
        ]

    @app.get("/reports/run-history", response_model=RunHistoryReport, dependencies=[Depends(require_read_api_key)])
    async def run_history_report(task_limit: int = 10, log_limit: int = 50, redact: bool | None = None) -> RunHistoryReport:
        return _build_run_history_report(task_limit=task_limit, log_limit=log_limit, redact=redact)

    @app.post("/reports/run-history/export", response_model=RunHistoryExportResponse, dependencies=[Depends(require_admin_api_key)])
    async def run_history_export(body: RunHistoryExportRequest) -> RunHistoryExportResponse:
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Export path blocked by execution policy")

        report = _build_run_history_report(task_limit=body.task_limit, log_limit=body.log_limit, redact=body.redact)
        payload = report.model_dump(mode="json")
        text = json.dumps(payload, indent=2, sort_keys=True)
        export_bytes = (text + "\n").encode("utf-8")
        max_export_bytes = int(runtime.config.get("reports.max_export_bytes", 262144))
        if len(export_bytes) > max_export_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Export payload exceeds limit ({len(export_bytes)} > {max_export_bytes})",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(export_bytes)

        runtime.logger.log(
            "REPORT_EXPORTED",
            {"path": str(target), "report_hash": report.report_hash, "source": "api"},
        )

        return RunHistoryExportResponse(
            ok=True,
            path=str(target),
            bytes_written=len(export_bytes),
            report_hash=report.report_hash,
        )

    @app.post("/reports/run-history/verify", response_model=RunHistoryVerifyResponse, dependencies=[Depends(require_read_api_key)])
    async def run_history_verify(body: RunHistoryVerifyRequest) -> RunHistoryVerifyResponse:
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Verify path blocked by execution policy")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Report file not found")

        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid report JSON: {exc}") from exc

        if not isinstance(loaded, dict):
            raise HTTPException(status_code=400, detail="Invalid report format")

        stored_hash = str(loaded.get("report_hash", ""))
        computed_hash = _compute_report_hash_from_payload(_signature_payload_from_report(loaded))
        valid = stored_hash == computed_hash

        runtime.logger.log(
            "REPORT_VERIFIED",
            {
                "path": str(target),
                "valid": valid,
                "stored_hash": stored_hash,
                "computed_hash": computed_hash,
                "source": "api",
            },
        )

        return RunHistoryVerifyResponse(
            ok=True,
            path=str(target),
            valid=valid,
            stored_hash=stored_hash,
            computed_hash=computed_hash,
            signing_version=str(loaded.get("signing_version")) if loaded.get("signing_version") is not None else None,
        )

    @app.post("/artifacts/cleanup", response_model=ArtifactCleanupResponse, dependencies=[Depends(require_admin_api_key)])
    async def artifacts_cleanup(body: ArtifactCleanupRequest) -> ArtifactCleanupResponse:
        report_default = int(runtime.config.get("reports.cleanup_max_age_days", 7))
        log_default = int(runtime.config.get("logging.cleanup_max_age_days", 30))
        effective_max_age_days = body.max_age_days or (min(report_default, log_default) if body.include_logs else report_default)
        deleted_paths, skipped_paths = _cleanup_artifacts(
            max_age_days=effective_max_age_days,
            include_logs=body.include_logs,
            dry_run=body.dry_run,
        )
        runtime.logger.log(
            "ARTIFACTS_CLEANUP",
            {
                "dry_run": body.dry_run,
                "include_logs": body.include_logs,
                "max_age_days": effective_max_age_days,
                "deleted_count": len(deleted_paths),
                "skipped_count": len(skipped_paths),
                "source": "api",
            },
        )
        return ArtifactCleanupResponse(
            ok=True,
            dry_run=body.dry_run,
            max_age_days=effective_max_age_days,
            deleted_paths=deleted_paths,
            skipped_paths=skipped_paths,
        )

    @app.get("/reports/policy", response_model=RunHistoryPolicy, dependencies=[Depends(require_read_api_key)])
    async def report_policy() -> RunHistoryPolicy:
        return RunHistoryPolicy(
            redact_by_default=bool(runtime.config.get("reports.redact_by_default", True)),
            redacted_keys=_report_redacted_keys(),
            max_export_bytes=int(runtime.config.get("reports.max_export_bytes", 262144)),
        )

    return app
