from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

from harness.api.schemas import (
    EmergencyAnalyzeRequest,
    EmergencyAnalyzeResponse,
    EmergencyConsensusEntry,
    EmergencyFixAction,
    EmergencyFixApplyRequest,
    EmergencyFixApplyResponse,
    EmergencyFixPlan,
    EmergencyFixRollbackRequest,
    EmergencyFixRollbackResponse,
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
    GraphifyRequest,
    GraphifyResponse,
    IngestionDedupeEntry,
    IngestionDedupeLogResponse,
    IngestionStatsResponse,
    EmergencyDiagnosisExportRequest,
    EmergencyDiagnosisExportResponse,
    EmergencyDiagnosis,
    EmergencyDiagnosisEntry,
    EmergencyDiagnosisQueryResponse,
    EmergencyDiagnosisSnapshot,
    EmergencyDiagnosisVerifyRequest,
    EmergencyDiagnosisVerifyResponse,
    EmergencyFixExecutionExportRequest,
    EmergencyFixExecutionExportResponse,
    EmergencyFixExecutionQueryResponse,
    EmergencyFixExecutionSnapshot,
    EmergencyFixExecutionVerifyRequest,
    EmergencyFixExecutionVerifyResponse,
    IncidentReport,
    IncidentReportExportRequest,
    IncidentReportExportResponse,
    IncidentReportVerifyRequest,
    IncidentReportVerifyResponse,
    LogEntry,
    LogQueryResponse,
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
    SchedulerMaintenanceRegisterResponse,
    SchedulerTickResponse,
    MemoryGraphNeighbors,
    MemoryGraphNodeHit,
    MemorySemanticHit,
    MemorySummary,
    SkillExecuteRequest,
    SkillExecuteResponse,
    SkillMarketInstallRequest,
    SkillMarketInstallResponse,
    SkillMarketItem,
    SkillMarketUninstallRequest,
    SkillMarketUninstallResponse,
    SkillMarketRemoteStatusResponse,
    SkillMarketRemoteSyncRequest,
    SkillMarketRemoteSyncResponse,
    SkillMarketUpdateRequest,
    SkillMarketUpdateResponse,
    SkillSummary,
    UiIngestionOverviewResponse,
    UiMarketOverviewResponse,
    TaskDetail,
    TaskSummary,
    ToolSummary,
)
from harness.scheduler.module import ScheduledJob
from harness.runtime.bootstrap import RuntimeContext, build_runtime
from harness.runtime.types import Task
from harness.skills.registry import SkillDefinition

T = TypeVar("T")


def create_app(workspace_root: Path) -> FastAPI:
    runtime: RuntimeContext = build_runtime(workspace_root)
    app = FastAPI(title="TitantShift Harness API", version="0.3.0")
    app.state.runtime = runtime
    emergency_fix_history: dict[str, dict[str, Any]] = {}

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
            "recent_diagnoses": report_data.get("recent_diagnoses"),
            "health": report_data.get("health"),
            "loaded_modules": report_data.get("loaded_modules"),
            "config_snapshot": report_data.get("config_snapshot"),
        }

    def _signature_payload_from_incident_report(report_data: dict[str, Any]) -> dict[str, Any]:
        generated_at = report_data.get("generated_at")
        if isinstance(generated_at, str) and generated_at.endswith("Z"):
            generated_at = generated_at[:-1] + "+00:00"
        return {
            "generated_at": generated_at,
            "signing_version": report_data.get("signing_version"),
            "scope": report_data.get("scope"),
            "execution_id": report_data.get("execution_id"),
            "task_id": report_data.get("task_id"),
            "agent_id": report_data.get("agent_id"),
            "linked_agent_ids": report_data.get("linked_agent_ids"),
            "task": report_data.get("task"),
            "agent": report_data.get("agent"),
            "executions": report_data.get("executions"),
            "fix_executions": report_data.get("fix_executions"),
            "correlation": report_data.get("correlation"),
            "module_errors": report_data.get("module_errors"),
            "diagnoses": report_data.get("diagnoses"),
            "related_events": report_data.get("related_events"),
        }

    def _signature_payload_from_diagnosis_snapshot(report_data: dict[str, Any]) -> dict[str, Any]:
        generated_at = report_data.get("generated_at")
        if isinstance(generated_at, str) and generated_at.endswith("Z"):
            generated_at = generated_at[:-1] + "+00:00"
        return {
            "generated_at": generated_at,
            "signing_version": report_data.get("signing_version"),
            "source": report_data.get("source"),
            "agent_id": report_data.get("agent_id"),
            "skill_id": report_data.get("skill_id"),
            "after": report_data.get("after"),
            "before": report_data.get("before"),
            "limit": report_data.get("limit"),
            "offset": report_data.get("offset"),
            "has_more": report_data.get("has_more"),
            "next_offset": report_data.get("next_offset"),
            "items": report_data.get("items"),
        }

    def _signature_payload_from_fix_execution_snapshot(report_data: dict[str, Any]) -> dict[str, Any]:
        generated_at = report_data.get("generated_at")
        if isinstance(generated_at, str) and generated_at.endswith("Z"):
            generated_at = generated_at[:-1] + "+00:00"
        return {
            "generated_at": generated_at,
            "signing_version": report_data.get("signing_version"),
            "execution_id": report_data.get("execution_id"),
            "failure_id": report_data.get("failure_id"),
            "after": report_data.get("after"),
            "before": report_data.get("before"),
            "limit": report_data.get("limit"),
            "offset": report_data.get("offset"),
            "has_more": report_data.get("has_more"),
            "next_offset": report_data.get("next_offset"),
            "items": report_data.get("items"),
        }

    def _build_run_history_report(task_limit: int, log_limit: int, redact: bool | None) -> RunHistoryReport:
        clamped_task_limit = max(1, min(task_limit, 100))
        clamped_log_limit = max(1, min(log_limit, 500))
        apply_redaction = bool(runtime.config.get("reports.redact_by_default", True)) if redact is None else redact
        redacted_keys = set(_report_redacted_keys())

        all_tasks = runtime.orchestrator.list_tasks()
        recent_tasks_raw = all_tasks[:clamped_task_limit]
        recent_events_raw = runtime.logger.query(limit=clamped_log_limit)
        recent_diagnoses_raw = runtime.logger.query(event_type="EMERGENCY_DIAGNOSIS", limit=clamped_log_limit)

        if apply_redaction and redacted_keys:
            recent_events_raw = [
                {
                    "timestamp": e.get("timestamp"),
                    "event_type": e.get("event_type"),
                    "payload": _redact_value(e.get("payload", {}), redacted_keys),
                }
                for e in recent_events_raw
            ]
            recent_diagnoses_raw = [
                {
                    "timestamp": e.get("timestamp"),
                    "event_type": e.get("event_type"),
                    "payload": _redact_value(e.get("payload", {}), redacted_keys),
                }
                for e in recent_diagnoses_raw
            ]

        failed_tasks = sum(1 for t in all_tasks if t.get("status") == "failed")
        loaded_modules = runtime.module_loader.list_modules()
        generated_at = datetime.now(timezone.utc)
        recent_tasks = [TaskSummary(**t) for t in recent_tasks_raw]
        recent_events = [LogEntry(**e) for e in recent_events_raw]
        recent_diagnoses = [
            EmergencyDiagnosisEntry(
                timestamp=str(e.get("timestamp", "")),
                source=str(dict(e.get("payload", {})).get("source", "unknown")),
                agent_id=(
                    str(dict(e.get("payload", {})).get("agent_id"))
                    if dict(e.get("payload", {})).get("agent_id") is not None
                    else None
                ),
                skill_id=(
                    str(dict(e.get("payload", {})).get("skill_id"))
                    if dict(e.get("payload", {})).get("skill_id") is not None
                    else None
                ),
                diagnoses=[EmergencyDiagnosis(**d) for d in list(dict(e.get("payload", {})).get("diagnoses", []))],
            )
            for e in recent_diagnoses_raw
        ]
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
            "recent_diagnoses": [r.model_dump(mode="json") for r in recent_diagnoses],
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
            recent_diagnoses=recent_diagnoses,
            health=runtime.health.as_list(),
            loaded_modules=loaded_modules,
            config_snapshot=config_snapshot,
        )

    def _agent_summary_from_record(agent: dict[str, Any]) -> AgentSummary:
        return AgentSummary(
            agent_id=str(agent["agent_id"]),
            role=str(agent["role"]),
            subagents_enabled=bool(runtime.config.get("orchestrator.enable_subagents", False)),
            model_default_backend=str(runtime.config.get("model.default_backend", "local_stub")),
            memory_layers=["working", "short_term", "long_term", "semantic", "graph"],
            assigned_skills=list(agent.get("assigned_skills", [])),
            allowed_tools=list(agent.get("allowed_tools", [])),
            spawned_from_task=agent.get("spawned_from_task"),
            created_at=agent.get("created_at"),
            active=bool(agent.get("active", True)),
        )

    def _diagnosis_entries_from_rows(rows: list[dict[str, Any]]) -> list[EmergencyDiagnosisEntry]:
        return [
            EmergencyDiagnosisEntry(
                timestamp=str(r.get("timestamp", "")),
                source=str(dict(r.get("payload", {})).get("source", "unknown")),
                agent_id=(
                    str(dict(r.get("payload", {})).get("agent_id"))
                    if dict(r.get("payload", {})).get("agent_id") is not None
                    else None
                ),
                skill_id=(
                    str(dict(r.get("payload", {})).get("skill_id"))
                    if dict(r.get("payload", {})).get("skill_id") is not None
                    else None
                ),
                diagnoses=[EmergencyDiagnosis(**d) for d in list(dict(r.get("payload", {})).get("diagnoses", []))],
            )
            for r in rows
        ]

    def _paginate(items: list[T], limit: int, offset: int) -> tuple[list[T], bool, int | None]:
        has_more = len(items) > limit
        trimmed = items[-limit:] if has_more else items
        next_offset = offset + len(trimmed) if has_more else None
        return trimmed, has_more, next_offset

    def _market_registry_path() -> Path:
        storage_root = workspace_root / str(runtime.config.get("memory.storage_dir", ".harness"))
        return storage_root / str(runtime.config.get("skills.market_registry_file", "skills_market_registry.json"))

    def _market_installed_path() -> Path:
        storage_root = workspace_root / str(runtime.config.get("memory.storage_dir", ".harness"))
        return storage_root / str(runtime.config.get("skills.market_installed_file", "skills_market_installed.json"))

    def _market_remote_cache_path() -> Path:
        storage_root = workspace_root / str(runtime.config.get("memory.storage_dir", ".harness"))
        return storage_root / str(runtime.config.get("skills.market_remote_cache_file", "skills_market_remote_cache.json"))

    def _market_remote_status_path() -> Path:
        storage_root = workspace_root / str(runtime.config.get("memory.storage_dir", ".harness"))
        return storage_root / str(runtime.config.get("skills.market_remote_status_file", "skills_market_remote_status.json"))

    def _skill_to_market_record(skill: SkillDefinition) -> dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "description": skill.description,
            "mode": skill.mode,
            "domain": skill.domain,
            "version": skill.version,
            "tags": list(skill.tags),
            "required_tools": list(skill.required_tools),
            "dependencies": list(skill.dependencies),
            "prompt_template": skill.prompt_template,
        }

    def _load_market_registry() -> dict[str, dict[str, Any]]:
        path = _market_registry_path()
        if not path.exists():
            seeded = [_skill_to_market_record(s) for s in runtime.skills.list_skills()]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seeded, indent=2, sort_keys=True), encoding="utf-8")
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = []
        if not isinstance(loaded, list):
            loaded = []
        out: dict[str, dict[str, Any]] = {}
        for item in loaded:
            if not isinstance(item, dict):
                continue
            skill_id = str(item.get("skill_id", "")).strip()
            if not skill_id:
                continue
            out[skill_id] = item
        return out

    def _save_market_registry(registry: dict[str, dict[str, Any]]) -> None:
        path = _market_registry_path()
        payload = [registry[k] for k in sorted(registry.keys())]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_market_installed(default_ids: list[str]) -> set[str]:
        path = _market_installed_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(default_ids, indent=2, sort_keys=True), encoding="utf-8")
            return set(default_ids)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = default_ids
        if not isinstance(loaded, list):
            loaded = default_ids
        return {str(v) for v in loaded if str(v).strip()}

    def _save_market_installed(installed_ids: set[str]) -> None:
        path = _market_installed_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(installed_ids), indent=2, sort_keys=True), encoding="utf-8")

    def _load_market_remote_status() -> dict[str, Any]:
        path = _market_remote_status_path()
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _save_market_remote_status(status: dict[str, Any]) -> None:
        path = _market_remote_status_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")

    def _normalize_market_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "skill_id": str(item.get("skill_id", "")).strip(),
            "description": str(item.get("description", "")),
            "mode": str(item.get("mode", "prompt")),
            "domain": str(item.get("domain", "general")),
            "version": str(item.get("version", "0.1.0")),
            "tags": [str(v) for v in list(item.get("tags", []))],
            "required_tools": [str(v) for v in list(item.get("required_tools", []))],
            "dependencies": [str(v) for v in list(item.get("dependencies", []))],
            "prompt_template": (
                str(item.get("prompt_template"))
                if item.get("prompt_template") is not None
                else None
            ),
        }

    def _market_signature_payload(
        *,
        source: str,
        generated_at: str,
        signing_version: str,
        items: list[Any],
    ) -> dict[str, Any]:
        return {
            "source": source,
            "generated_at": generated_at,
            "signing_version": signing_version,
            "items": items,
        }

    def _verify_ed25519_signature(
        *,
        signature_payload: dict[str, Any],
        signature_b64: str,
        trusted_public_keys: list[str],
    ) -> bool:
        try:
            from nacl.encoding import Base64Encoder
            from nacl.signing import VerifyKey
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="Ed25519 verification requires pynacl package",
            ) from exc

        payload_bytes = json.dumps(
            signature_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        for key_b64 in trusted_public_keys:
            candidate = key_b64.strip()
            if not candidate:
                continue
            try:
                verify_key = VerifyKey(candidate, encoder=Base64Encoder)
                verify_key.verify(payload_bytes, Base64Encoder.decode(signature_b64))
                return True
            except Exception:
                continue
        return False

    async def _fetch_remote_market_index(source: str) -> dict[str, Any]:
        source_value = source.strip()
        if source_value.startswith("file://"):
            raw = Path(source_value.removeprefix("file://")).read_text(encoding="utf-8")
        elif Path(source_value).exists():
            raw = Path(source_value).read_text(encoding="utf-8")
        else:
            timeout_s = float(runtime.config.get("skills.market_remote_timeout_s", 10.0))
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(source_value)
                response.raise_for_status()
                raw = response.text
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise HTTPException(status_code=400, detail="Remote index must be a JSON object")
        return loaded

    def _market_to_skill_definition(item: dict[str, Any]) -> SkillDefinition:
        return SkillDefinition(
            skill_id=str(item.get("skill_id", "")),
            description=str(item.get("description", "")),
            mode=str(item.get("mode", "prompt")),
            domain=str(item.get("domain", "general")),
            version=str(item.get("version", "0.1.0")),
            tags=[str(v) for v in list(item.get("tags", []))],
            required_tools=[str(v) for v in list(item.get("required_tools", []))],
            dependencies=[str(v) for v in list(item.get("dependencies", []))],
            prompt_template=(
                str(item.get("prompt_template"))
                if item.get("prompt_template") is not None
                else None
            ),
        )

    def _market_missing_tools(item: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for tool_name in [str(v) for v in list(item.get("required_tools", []))]:
            if runtime.tools.get_tool(tool_name) is None:
                missing.append(tool_name)
        return missing

    market_registry = _load_market_registry()
    market_installed = _load_market_installed([s.skill_id for s in runtime.skills.list_skills()])

    # Reconcile runtime skill registry with persisted installed-state.
    for current in list(runtime.skills.list_skills()):
        if current.skill_id not in market_installed:
            runtime.skills.unregister_skill(current.skill_id)
    for installed_id in sorted(market_installed):
        if runtime.skills.get_skill(installed_id) is None and installed_id in market_registry:
            runtime.skills.register_skill(_market_to_skill_definition(market_registry[installed_id]))

    def _current_market_rows() -> list[SkillMarketItem]:
        installed_set = set(market_installed)
        rows: list[SkillMarketItem] = []
        for skill_id, item in sorted(market_registry.items(), key=lambda kv: kv[0]):
            dependencies = [str(v) for v in list(item.get("dependencies", []))]
            missing_dependencies = sorted([dep for dep in dependencies if dep not in installed_set])
            missing_tools = sorted(_market_missing_tools(item))
            rows.append(
                SkillMarketItem(
                    skill_id=skill_id,
                    description=str(item.get("description", "")),
                    mode=str(item.get("mode", "prompt")),
                    domain=str(item.get("domain", "general")),
                    version=str(item.get("version", "0.1.0")),
                    tags=[str(v) for v in list(item.get("tags", []))],
                    required_tools=[str(v) for v in list(item.get("required_tools", []))],
                    dependencies=dependencies,
                    installed=skill_id in installed_set,
                    installable=(len(missing_dependencies) == 0 and len(missing_tools) == 0),
                    missing_dependencies=missing_dependencies,
                    missing_tools=missing_tools,
                )
            )
        return rows

    def _current_market_remote_status() -> SkillMarketRemoteStatusResponse:
        status = _load_market_remote_status()
        if not status:
            return SkillMarketRemoteStatusResponse(synced=False)
        return SkillMarketRemoteStatusResponse(
            synced=True,
            source=str(status.get("source")) if status.get("source") is not None else None,
            synced_at=str(status.get("synced_at")) if status.get("synced_at") is not None else None,
            pulled_count=int(status.get("pulled_count", 0)),
            index_hash=str(status.get("index_hash")) if status.get("index_hash") is not None else None,
        )

    def _build_incident_report(
        *,
        task_id: str | None,
        agent_id: str | None,
        execution_id: str | None,
        include_fix_executions: bool,
        fix_event_type: str | None,
        after: str | None,
        before: str | None,
        offset: int,
        limit: int,
    ) -> IncidentReport:
        if not task_id and not agent_id and not execution_id:
            raise HTTPException(status_code=400, detail="Provide task_id, agent_id, or execution_id")

        requested_execution_scope = execution_id is not None and task_id is None and agent_id is None
        clamped_limit = max(1, min(limit, 500))
        normalized_fix_event_type = (fix_event_type or "all").strip().lower()
        if normalized_fix_event_type not in {"all", "apply", "rollback"}:
            raise HTTPException(status_code=400, detail="Invalid fix_event_type: expected all, apply, or rollback")
        selected_fix_event_types = {
            "EMERGENCY_FIX_APPLY",
            "EMERGENCY_FIX_ROLLBACK",
        }
        if normalized_fix_event_type == "apply":
            selected_fix_event_types = {"EMERGENCY_FIX_APPLY"}
        elif normalized_fix_event_type == "rollback":
            selected_fix_event_types = {"EMERGENCY_FIX_ROLLBACK"}

        linked_agent_ids: list[str] = []
        task_detail: TaskDetail | None = None
        agent_summary: AgentSummary | None = None

        if execution_id:
            execution_rows = runtime.logger.query(
                event_type="AGENT_SKILL_EXECUTED",
                execution_id=execution_id,
                after=after,
                before=before,
                limit=1,
            )
            if execution_rows:
                execution_payload = dict(execution_rows[-1].get("payload", {}))
                inferred_agent_id = execution_payload.get("agent_id")
                if inferred_agent_id and not agent_id:
                    agent_id = str(inferred_agent_id)
            else:
                fix_rows = runtime.logger.query(
                    event_type="EMERGENCY_FIX_APPLY",
                    execution_id=execution_id,
                    after=after,
                    before=before,
                    limit=1,
                )
                if not fix_rows:
                    raise HTTPException(status_code=404, detail="Execution not found")

        if task_id:
            task = runtime.orchestrator.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            task_detail = TaskDetail(**task)
            spawn_rows = runtime.logger.query(
                event_type="AGENT_SPAWNED",
                task_id=task_id,
                after=after,
                before=before,
                offset=offset,
                limit=clamped_limit,
            )
            linked_agent_ids = [
                str(dict(row.get("payload", {})).get("agent_id"))
                for row in spawn_rows
                if dict(row.get("payload", {})).get("agent_id")
            ]
        if agent_id:
            agent = runtime.orchestrator.get_agent(agent_id)
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            agent_record = next((row for row in runtime.orchestrator.list_agents() if row.get("agent_id") == agent_id), None)
            if agent_record is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            agent_summary = _agent_summary_from_record(agent_record)
            linked_agent_ids = sorted(set(linked_agent_ids + [agent_id]))
            if agent.spawned_from_task:
                task = runtime.orchestrator.get_task(agent.spawned_from_task)
                if task is not None:
                    task_detail = TaskDetail(**task)

        if not linked_agent_ids and agent_id:
            linked_agent_ids = [agent_id]

        executions_rows: list[dict[str, Any]] = []
        diagnosis_rows: list[dict[str, Any]] = []
        fix_execution_rows: list[dict[str, Any]] = []
        module_error_rows: list[dict[str, Any]] = []
        related_event_rows: list[dict[str, Any]] = []

        if task_id:
            related_event_rows.extend(
                runtime.logger.query(task_id=task_id, after=after, before=before, offset=offset, limit=clamped_limit)
            )
            module_error_rows.extend(
                runtime.logger.query(
                    event_type="MODULE_ERROR",
                    task_id=task_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )

        for linked_agent_id in linked_agent_ids:
            executions_rows.extend(
                runtime.logger.query(
                    event_type="AGENT_SKILL_EXECUTED",
                    agent_id=linked_agent_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )
            diagnosis_rows.extend(
                runtime.logger.query(
                    event_type="EMERGENCY_DIAGNOSIS",
                    agent_id=linked_agent_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )
            module_error_rows.extend(
                runtime.logger.query(
                    event_type="MODULE_ERROR",
                    agent_id=linked_agent_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )

        if include_fix_executions and execution_id:
            fix_execution_rows.extend(
                runtime.logger.query(
                    event_type="EMERGENCY_FIX_APPLY",
                    execution_id=execution_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )
            fix_execution_rows.extend(
                runtime.logger.query(
                    event_type="EMERGENCY_FIX_ROLLBACK",
                    execution_id=execution_id,
                    after=after,
                    before=before,
                    offset=offset,
                    limit=clamped_limit,
                )
            )

        failure_ids: set[str] = set()
        for row in diagnosis_rows:
            payload = dict(row.get("payload", {}))
            failure_id = payload.get("failure_id")
            if failure_id:
                failure_ids.add(str(failure_id))
        for row in related_event_rows:
            payload = dict(row.get("payload", {}))
            failure_id = payload.get("failure_id")
            if failure_id:
                failure_ids.add(str(failure_id))
        if include_fix_executions and failure_ids:
            candidate_fix_rows: list[dict[str, Any]] = []
            if "EMERGENCY_FIX_APPLY" in selected_fix_event_types:
                candidate_fix_rows.extend(
                    runtime.logger.query(
                        event_type="EMERGENCY_FIX_APPLY",
                        after=after,
                        before=before,
                        offset=offset,
                        limit=clamped_limit,
                    )
                )
            if "EMERGENCY_FIX_ROLLBACK" in selected_fix_event_types:
                candidate_fix_rows.extend(
                    runtime.logger.query(
                        event_type="EMERGENCY_FIX_ROLLBACK",
                        after=after,
                        before=before,
                        offset=offset,
                        limit=clamped_limit,
                    )
                )
            for row in candidate_fix_rows:
                payload = dict(row.get("payload", {}))
                candidate_failure_id = payload.get("failure_id")
                if candidate_failure_id and str(candidate_failure_id) in failure_ids:
                    fix_execution_rows.append(row)

        if include_fix_executions and selected_fix_event_types != {"EMERGENCY_FIX_APPLY", "EMERGENCY_FIX_ROLLBACK"}:
            fix_execution_rows = [
                row for row in fix_execution_rows if str(row.get("event_type", "")) in selected_fix_event_types
            ]
        if not include_fix_executions:
            fix_execution_rows = []

        dedupe = lambda rows: list({json.dumps(r, sort_keys=True): r for r in rows}.values())
        deduped_executions = dedupe(executions_rows)
        deduped_fix_executions = dedupe(fix_execution_rows)
        deduped_module_errors = dedupe(module_error_rows)
        deduped_diagnoses = dedupe(diagnosis_rows)
        deduped_related_events = dedupe(related_event_rows)
        correlation_warnings: list[str] = []
        if len(failure_ids) > 1:
            correlation_warnings.append("multiple_failure_ids_detected")
        if not include_fix_executions:
            correlation_warnings.append("fix_executions_excluded_by_filter")
        elif normalized_fix_event_type != "all":
            correlation_warnings.append(f"fix_event_type_filtered:{normalized_fix_event_type}")
        generated_at = datetime.now(timezone.utc)
        signing_version = "v1"
        payload = {
            "generated_at": generated_at.isoformat(),
            "signing_version": signing_version,
            "scope": "execution" if requested_execution_scope else "agent" if agent_id and not task_id else "task" if task_id and not agent_id else "mixed",
            "execution_id": execution_id,
            "task_id": task_id or (task_detail.task_id if task_detail else None),
            "agent_id": agent_id,
            "linked_agent_ids": sorted(set(linked_agent_ids)),
            "task": task_detail.model_dump(mode="json") if task_detail else None,
            "agent": agent_summary.model_dump(mode="json") if agent_summary else None,
            "executions": [LogEntry(**row).model_dump(mode="json") for row in deduped_executions],
            "fix_executions": [LogEntry(**row).model_dump(mode="json") for row in deduped_fix_executions],
            "correlation": {
                "failure_ids": sorted(failure_ids),
                "fix_execution_count": len(deduped_fix_executions),
                "correlation_sources": [
                    source
                    for source in [
                        "from_execution_id" if include_fix_executions and execution_id else None,
                        "from_failure_id" if include_fix_executions and bool(failure_ids) else None,
                    ]
                    if source is not None
                ],
                "resolved_execution_ids": sorted(
                    {
                        str(dict(row.get("payload", {})).get("execution_id"))
                        for row in deduped_fix_executions
                        if dict(row.get("payload", {})).get("execution_id")
                    }
                ),
                "warnings": correlation_warnings,
            },
            "module_errors": [LogEntry(**row).model_dump(mode="json") for row in deduped_module_errors],
            "diagnoses": [r.model_dump(mode="json") for r in _diagnosis_entries_from_rows(deduped_diagnoses)],
            "related_events": [LogEntry(**row).model_dump(mode="json") for row in deduped_related_events],
        }
        report_hash = _compute_report_hash_from_payload(payload)
        return IncidentReport(report_hash=report_hash, **payload)

    def _build_diagnosis_snapshot(
        *,
        source: str | None,
        agent_id: str | None,
        skill_id: str | None,
        after: str | None,
        before: str | None,
        offset: int,
        limit: int,
    ) -> EmergencyDiagnosisSnapshot:
        clamped_limit = max(1, min(limit, 500))
        rows = runtime.logger.query(
            event_type="EMERGENCY_DIAGNOSIS",
            source=source,
            agent_id=agent_id,
            skill_id=skill_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit + 1,
        )
        items, has_more, next_offset = _paginate(_diagnosis_entries_from_rows(rows), clamped_limit, offset)
        generated_at = datetime.now(timezone.utc)
        signing_version = "v1"
        payload = {
            "generated_at": generated_at.isoformat(),
            "signing_version": signing_version,
            "source": source,
            "agent_id": agent_id,
            "skill_id": skill_id,
            "after": after,
            "before": before,
            "limit": clamped_limit,
            "offset": max(0, offset),
            "has_more": has_more,
            "next_offset": next_offset,
            "items": [item.model_dump(mode="json") for item in items],
        }
        report_hash = _compute_report_hash_from_payload(payload)
        return EmergencyDiagnosisSnapshot(report_hash=report_hash, **payload)

    def _build_fix_execution_snapshot(
        *,
        execution_id: str | None,
        failure_id: str | None,
        after: str | None,
        before: str | None,
        offset: int,
        limit: int,
    ) -> EmergencyFixExecutionSnapshot:
        clamped_limit = max(1, min(limit, 500))
        rows = runtime.logger.query(
            event_type="EMERGENCY_FIX_APPLY",
            execution_id=execution_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit + 1,
        ) + runtime.logger.query(
            event_type="EMERGENCY_FIX_ROLLBACK",
            execution_id=execution_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit + 1,
        )
        rows.sort(key=lambda r: str(r.get("timestamp", "")))
        filtered = rows
        if failure_id:
            filtered = [
                row
                for row in filtered
                if str(dict(row.get("payload", {})).get("failure_id", "")) == failure_id
            ]

        items, has_more, next_offset = _paginate([LogEntry(**r) for r in filtered], clamped_limit, offset)
        generated_at = datetime.now(timezone.utc)
        signing_version = "v1"
        payload = {
            "generated_at": generated_at.isoformat(),
            "signing_version": signing_version,
            "execution_id": execution_id,
            "failure_id": failure_id,
            "after": after,
            "before": before,
            "limit": clamped_limit,
            "offset": max(0, offset),
            "has_more": has_more,
            "next_offset": next_offset,
            "items": [item.model_dump(mode="json") for item in items],
        }
        report_hash = _compute_report_hash_from_payload(payload)
        return EmergencyFixExecutionSnapshot(report_hash=report_hash, **payload)

    def _storage_root() -> Path:
        return runtime.logger.log_file.parent.resolve()

    def _parse_iso_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {value}")

    def _validate_time_window(after: str | None, before: str | None) -> None:
        after_dt = _parse_iso_timestamp(after)
        before_dt = _parse_iso_timestamp(before)
        if after_dt and before_dt and after_dt > before_dt:
            raise HTTPException(status_code=400, detail="Invalid time window: 'after' must be <= 'before'")

    def _candidate_cleanup_paths(include_logs: bool) -> list[Path]:
        root = _storage_root()
        report_glob = str(runtime.config.get("reports.cleanup_glob", "*.json"))
        candidates = [path for path in root.glob(report_glob) if path.is_file()]
        if include_logs and runtime.logger.log_file.exists():
            candidates.append(runtime.logger.log_file.resolve())
        deduped: dict[str, Path] = {str(path.resolve()): path.resolve() for path in candidates}
        return list(deduped.values())

    def _recompute_agent_tools(agent_id: str) -> None:
        agent = runtime.orchestrator.get_agent(agent_id)
        if agent is None:
            return
        allowed_tools = sorted(
            {
                tool_name
                for sid in list(agent.assigned_skills)
                for tool_name in (
                    runtime.skills.get_skill(sid).required_tools if runtime.skills.get_skill(sid) is not None else []
                )
            }
        )
        agent.allowed_tools = allowed_tools

    def _apply_fix_action(action: EmergencyFixAction, *, dry_run: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if action.action_type == "restart_module":
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "queued",
            }, None

        if action.action_type == "restart_agent":
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "queued",
            }, None

        if action.action_type == "disable_skill":
            changed_agents: list[str] = []
            for agent in runtime.orchestrator.agents.values():
                if action.target_id and action.target_id in agent.assigned_skills:
                    changed_agents.append(agent.agent_id)
                    if not dry_run:
                        agent.assigned_skills = [s for s in agent.assigned_skills if s != action.target_id]
                        _recompute_agent_tools(agent.agent_id)
            rollback_action = {
                "action_type": "restore_agent_skill_assignments",
                "params": {"skill_id": action.target_id, "agent_ids": changed_agents},
            }
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "applied",
                "changed_agents": changed_agents,
            }, rollback_action

        if action.action_type == "enable_skill":
            target_skill = str(action.target_id or "")
            changed_agents: list[str] = []
            preferred_agent_id = str(action.params.get("agent_id", "")) if action.params else ""
            if target_skill:
                for agent in runtime.orchestrator.agents.values():
                    if preferred_agent_id and agent.agent_id != preferred_agent_id:
                        continue
                    if target_skill not in agent.assigned_skills:
                        changed_agents.append(agent.agent_id)
                        if not dry_run:
                            agent.assigned_skills = sorted(set(agent.assigned_skills + [target_skill]))
                            _recompute_agent_tools(agent.agent_id)
                    if preferred_agent_id:
                        break
            rollback_action = {
                "action_type": "remove_agent_skill_assignments",
                "params": {"skill_id": target_skill, "agent_ids": changed_agents},
            }
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "applied",
                "changed_agents": changed_agents,
            }, rollback_action

        if action.action_type == "disable_tool":
            tool_name = str(action.target_id or "")
            prior = {
                "in_blocked": tool_name in runtime.tools.policy.blocked_tool_names,
                "in_allowed": tool_name in runtime.tools.policy.allowed_tool_names,
            }
            if tool_name:
                if not dry_run:
                    runtime.tools.policy.blocked_tool_names.add(tool_name)
                    runtime.tools.policy.allowed_tool_names.discard(tool_name)
            rollback_action = {
                "action_type": "restore_tool_policy_state",
                "params": {"tool_name": tool_name, **prior},
            }
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "applied",
            }, rollback_action

        if action.action_type == "enable_tool":
            tool_name = str(action.target_id or "")
            prior = {
                "in_blocked": tool_name in runtime.tools.policy.blocked_tool_names,
                "in_allowed": tool_name in runtime.tools.policy.allowed_tool_names,
            }
            if tool_name and not dry_run:
                runtime.tools.policy.blocked_tool_names.discard(tool_name)
                runtime.tools.policy.allowed_tool_names.add(tool_name)
            rollback_action = {
                "action_type": "restore_tool_policy_state",
                "params": {"tool_name": tool_name, **prior},
            }
            return {
                "action_type": action.action_type,
                "target_id": action.target_id,
                "status": "simulated" if dry_run else "applied",
            }, rollback_action

        if action.action_type == "update_config":
            key = str(action.params.get("key", "")) if action.params else ""
            value = action.params.get("value") if action.params else None
            old_value = runtime.config.get(key) if key else None
            if key and not dry_run:
                runtime.config.set(key, value)
            rollback_action = {
                "action_type": "update_config",
                "params": {"key": key, "value": old_value},
            }
            return {
                "action_type": action.action_type,
                "status": "simulated" if dry_run else "applied",
                "key": key,
            }, rollback_action

        if action.action_type == "restore_tool_policy_state":
            params = action.params or {}
            tool_name = str(params.get("tool_name", ""))
            in_blocked = bool(params.get("in_blocked", False))
            in_allowed = bool(params.get("in_allowed", False))
            if tool_name and not dry_run:
                if in_blocked:
                    runtime.tools.policy.blocked_tool_names.add(tool_name)
                else:
                    runtime.tools.policy.blocked_tool_names.discard(tool_name)
                if in_allowed:
                    runtime.tools.policy.allowed_tool_names.add(tool_name)
                else:
                    runtime.tools.policy.allowed_tool_names.discard(tool_name)
            return {
                "action_type": action.action_type,
                "target_id": tool_name,
                "status": "simulated" if dry_run else "applied",
            }, None

        if action.action_type in ["restore_agent_skill_assignments", "remove_agent_skill_assignments"]:
            params = action.params or {}
            target_skill = str(params.get("skill_id", ""))
            agent_ids = [str(a) for a in list(params.get("agent_ids", []))]
            changed_agents: list[str] = []
            for agent_id in agent_ids:
                agent = runtime.orchestrator.get_agent(agent_id)
                if agent is None:
                    continue
                if action.action_type == "restore_agent_skill_assignments":
                    if target_skill and target_skill not in agent.assigned_skills:
                        changed_agents.append(agent.agent_id)
                        if not dry_run:
                            agent.assigned_skills = sorted(set(agent.assigned_skills + [target_skill]))
                            _recompute_agent_tools(agent.agent_id)
                else:
                    if target_skill and target_skill in agent.assigned_skills:
                        changed_agents.append(agent.agent_id)
                        if not dry_run:
                            agent.assigned_skills = [s for s in agent.assigned_skills if s != target_skill]
                            _recompute_agent_tools(agent.agent_id)
            return {
                "action_type": action.action_type,
                "target_id": target_skill,
                "status": "simulated" if dry_run else "applied",
                "changed_agents": changed_agents,
            }, None

        return {
            "action_type": action.action_type,
            "target_id": action.target_id,
            "status": "unsupported",
        }, None

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

    def _register_maintenance_jobs() -> list[str]:
        registered: list[str] = []

        async def _health_snapshot_job() -> None:
            statuses = runtime.health.as_list()
            degraded = [row for row in statuses if row.get("status") != "healthy"]
            runtime.logger.log(
                "MAINTENANCE_HEALTH_SNAPSHOT",
                {
                    "source": "scheduler.maintenance",
                    "total_modules": len(statuses),
                    "degraded_modules": len(degraded),
                },
            )

        async def _retention_preview_job() -> None:
            report_default = int(runtime.config.get("reports.cleanup_max_age_days", 7))
            cutoff = datetime.now(timezone.utc) - timedelta(days=report_default)
            candidates = [
                p
                for p in _candidate_cleanup_paths(include_logs=False)
                if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) <= cutoff
            ]
            runtime.logger.log(
                "MAINTENANCE_RETENTION_PREVIEW",
                {
                    "source": "scheduler.maintenance",
                    "max_age_days": report_default,
                    "candidate_count": len(candidates),
                },
            )

        if runtime.scheduler.get_job("maintenance_health_snapshot") is None:
            runtime.scheduler.register_job(
                ScheduledJob(
                    job_id="maintenance_health_snapshot",
                    description="Periodic health snapshot for maintenance telemetry",
                    schedule_type="interval",
                    interval_seconds=int(runtime.config.get("scheduler.maintenance_health_interval_s", 300)),
                    callback=_health_snapshot_job,
                )
            )
            registered.append("maintenance_health_snapshot")

        if runtime.scheduler.get_job("maintenance_retention_preview") is None:
            runtime.scheduler.register_job(
                ScheduledJob(
                    job_id="maintenance_retention_preview",
                    description="Periodic artifact-retention preview (non-destructive)",
                    schedule_type="interval",
                    interval_seconds=int(runtime.config.get("scheduler.maintenance_retention_interval_s", 1800)),
                    callback=_retention_preview_job,
                )
            )
            registered.append("maintenance_retention_preview")

        return registered

    if bool(runtime.config.get("scheduler.enable_maintenance_jobs", False)):
        _register_maintenance_jobs()

    async def _resolve_model_connection() -> tuple[bool, str]:
        backend = str(runtime.config.get("model.default_backend", "local_stub"))

        if backend == "local_stub":
            return True, "local stub backend"

        if backend == "lmstudio":
            base_url = str(runtime.config.get("model.lmstudio.base_url", "http://127.0.0.1:1234/v1")).rstrip("/")
            models_url = f"{base_url}/models"
            configured_model = str(runtime.config.get("model.lmstudio.model", "")).strip()
            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    response = await client.get(models_url)
                    response.raise_for_status()
                    body = response.json()
                listed = [str(m.get("id", "")) for m in body.get("data", []) if isinstance(m, dict)]
                if configured_model and configured_model not in listed:
                    return False, f"configured model not loaded: {configured_model}"
                return True, "LM Studio reachable"
            except Exception as exc:
                return False, f"LM Studio unreachable: {exc}"

        if backend == "openai_compatible":
            return False, "openai_compatible is scaffold-only in this build"

        return False, f"unsupported backend: {backend}"

    @app.get("/status", dependencies=[Depends(require_read_api_key)])
    async def status() -> dict:
        model_connected, model_reason = await _resolve_model_connection()
        runtime.health.set(
            "models",
            "healthy" if model_connected else "unhealthy",
            {
                "default": runtime.config.get("model.default_backend"),
                "connected": model_connected,
                "reason": model_reason,
            },
        )
        return {
            "ok": True,
            "subagents_enabled": runtime.config.get("orchestrator.enable_subagents"),
            "graph_backend": runtime.config.get("memory.graph_backend"),
            "semantic_backend": runtime.config.get("memory.semantic_backend"),
            "default_model_backend": runtime.config.get("model.default_backend"),
            "model_connected": model_connected,
            "model_connection_reason": model_reason,
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

    @app.get("/logs", response_model=LogQueryResponse, dependencies=[Depends(require_read_api_key)])
    async def get_logs(
        event_type: str | None = None,
        task_id: str | None = None,
        source: str | None = None,
        agent_id: str | None = None,
        skill_id: str | None = None,
        execution_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> LogQueryResponse:
        _validate_time_window(after, before)
        clamped_limit = max(1, min(limit, 1000))
        rows = runtime.logger.query(
            event_type=event_type,
            task_id=task_id,
            source=source,
            agent_id=agent_id,
            skill_id=skill_id,
            execution_id=execution_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit + 1,
        )
        items, has_more, next_offset = _paginate([LogEntry(**r) for r in rows], clamped_limit, offset)
        return LogQueryResponse(items=items, limit=clamped_limit, offset=max(0, offset), has_more=has_more, next_offset=next_offset)

    @app.get("/diagnostics/emergency", response_model=EmergencyDiagnosisQueryResponse, dependencies=[Depends(require_read_api_key)])
    async def get_emergency_diagnoses(
        source: str | None = None,
        agent_id: str | None = None,
        skill_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> EmergencyDiagnosisQueryResponse:
        _validate_time_window(after, before)
        clamped_limit = max(1, min(limit, 200))
        rows = runtime.logger.query(
            event_type="EMERGENCY_DIAGNOSIS",
            source=source,
            agent_id=agent_id,
            skill_id=skill_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit + 1,
        )
        items, has_more, next_offset = _paginate(_diagnosis_entries_from_rows(rows), clamped_limit, offset)
        return EmergencyDiagnosisQueryResponse(items=items, limit=clamped_limit, offset=max(0, offset), has_more=has_more, next_offset=next_offset)

    @app.get(
        "/diagnostics/emergency/fix-executions",
        response_model=EmergencyFixExecutionQueryResponse,
        dependencies=[Depends(require_read_api_key)],
    )
    async def get_emergency_fix_executions(
        execution_id: str | None = None,
        failure_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> EmergencyFixExecutionQueryResponse:
        _validate_time_window(after, before)
        clamped_limit = max(1, min(limit, 200))
        snapshot = _build_fix_execution_snapshot(
            execution_id=execution_id,
            failure_id=failure_id,
            after=after,
            before=before,
            offset=offset,
            limit=clamped_limit,
        )
        return EmergencyFixExecutionQueryResponse(
            items=snapshot.items,
            limit=snapshot.limit,
            offset=snapshot.offset,
            has_more=snapshot.has_more,
            next_offset=snapshot.next_offset,
        )

    @app.post(
        "/diagnostics/emergency/analyze",
        response_model=EmergencyAnalyzeResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def analyze_emergency_failure(body: EmergencyAnalyzeRequest) -> EmergencyAnalyzeResponse:
        payload = {
            "source": body.source,
            "error": body.error,
            "agent_id": body.agent_id,
            "skill_id": body.skill_id,
            **body.context,
        }
        analysis = await runtime.emergency.analyze_failure(payload)
        runtime.logger.log(
            "EMERGENCY_DIAGNOSIS",
            {
                "source": body.source,
                "agent_id": body.agent_id,
                "skill_id": body.skill_id,
                "failure_id": analysis.failure_id,
                "diagnoses": [
                    {
                        "hypothesis": d.hypothesis,
                        "confidence": d.confidence,
                        "suggested_fix": d.suggested_fix,
                    }
                    for d in analysis.diagnoses
                ],
            },
        )
        runtime.logger.log(
            "EMERGENCY_FIX_PLAN",
            {
                "failure_id": analysis.failure_id,
                "source": body.source,
                "risk_level": analysis.fix_plan.risk_level,
                "requires_user_approval": analysis.fix_plan.requires_user_approval,
                "actions": [
                    {
                        "action_type": a.action_type,
                        "target_id": a.target_id,
                        "params": a.params or {},
                    }
                    for a in analysis.fix_plan.actions
                ],
            },
        )
        return EmergencyAnalyzeResponse(
            ok=True,
            failure_id=analysis.failure_id,
            diagnoses=[
                EmergencyDiagnosis(
                    hypothesis=d.hypothesis,
                    confidence=d.confidence,
                    suggested_fix=d.suggested_fix,
                )
                for d in analysis.diagnoses
            ],
            selected_hypothesis=analysis.selected_hypothesis,
            consensus=[EmergencyConsensusEntry(**entry) for entry in analysis.consensus],
            fix_plan=EmergencyFixPlan(
                failure_id=analysis.fix_plan.failure_id,
                recommended_hypothesis=analysis.fix_plan.recommended_hypothesis,
                risk_level=analysis.fix_plan.risk_level,
                requires_user_approval=analysis.fix_plan.requires_user_approval,
                actions=[
                    EmergencyFixAction(action_type=a.action_type, target_id=a.target_id, params=a.params or {})
                    for a in analysis.fix_plan.actions
                ],
                notes=analysis.fix_plan.notes,
            ),
        )

    @app.post(
        "/diagnostics/emergency/fix-apply",
        response_model=EmergencyFixApplyResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def apply_emergency_fix(body: EmergencyFixApplyRequest) -> EmergencyFixApplyResponse:
        if not body.approved:
            raise HTTPException(status_code=400, detail="Fix application requires approved=true")

        execution_id = f"fix-{uuid.uuid4().hex[:12]}"
        results: list[dict[str, Any]] = []
        rollback_actions: list[dict[str, Any]] = []
        for action in body.fix_plan.actions:
            result, rollback_action = _apply_fix_action(action, dry_run=body.dry_run)
            results.append(result)
            if rollback_action is not None:
                rollback_actions.append(rollback_action)

        rollback_available = (not body.dry_run) and len(rollback_actions) > 0
        if rollback_available:
            emergency_fix_history[execution_id] = {
                "execution_id": execution_id,
                "failure_id": body.fix_plan.failure_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rollback_actions": rollback_actions,
                "rolled_back": False,
            }

        runtime.logger.log(
            "EMERGENCY_FIX_APPLY",
            {
                "execution_id": execution_id,
                "failure_id": body.fix_plan.failure_id,
                "approved": body.approved,
                "dry_run": body.dry_run,
                "rollback_available": rollback_available,
                "results": results,
                "source": "api",
            },
        )
        return EmergencyFixApplyResponse(
            ok=True,
            applied=not body.dry_run,
            dry_run=body.dry_run,
            execution_id=execution_id,
            rollback_available=rollback_available,
            results=results,
            message="Fix actions simulated" if body.dry_run else "Fix actions applied",
        )

    @app.post(
        "/diagnostics/emergency/fix-rollback",
        response_model=EmergencyFixRollbackResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def rollback_emergency_fix(body: EmergencyFixRollbackRequest) -> EmergencyFixRollbackResponse:
        record = emergency_fix_history.get(body.execution_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Fix execution not found")
        if bool(record.get("rolled_back", False)):
            raise HTTPException(status_code=400, detail="Fix execution already rolled back")

        rollback_actions = list(record.get("rollback_actions", []))
        if not rollback_actions:
            raise HTTPException(status_code=400, detail="No rollback actions available for this execution")

        results: list[dict[str, Any]] = []
        for action_dict in reversed(rollback_actions):
            action = EmergencyFixAction(
                action_type=str(action_dict.get("action_type", "")),
                target_id=(str(action_dict.get("target_id")) if action_dict.get("target_id") is not None else None),
                params=dict(action_dict.get("params", {})),
            )
            result, _ = _apply_fix_action(action, dry_run=body.dry_run)
            results.append(result)

        if not body.dry_run:
            record["rolled_back"] = True
            record["rolled_back_at"] = datetime.now(timezone.utc).isoformat()

        runtime.logger.log(
            "EMERGENCY_FIX_ROLLBACK",
            {
                "execution_id": body.execution_id,
                "failure_id": record.get("failure_id"),
                "dry_run": body.dry_run,
                "rolled_back": not body.dry_run,
                "results": results,
                "source": "api",
            },
        )
        return EmergencyFixRollbackResponse(
            ok=True,
            rolled_back=not body.dry_run,
            dry_run=body.dry_run,
            execution_id=body.execution_id,
            results=results,
            message="Rollback actions simulated" if body.dry_run else "Rollback actions applied",
        )

    @app.get("/reports/incident", response_model=IncidentReport, dependencies=[Depends(require_read_api_key)])
    async def incident_report(
        task_id: str | None = None,
        agent_id: str | None = None,
        execution_id: str | None = None,
        include_fix_executions: bool = True,
        fix_event_type: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> IncidentReport:
        _validate_time_window(after, before)
        return _build_incident_report(
            task_id=task_id,
            agent_id=agent_id,
            execution_id=execution_id,
            include_fix_executions=include_fix_executions,
            fix_event_type=fix_event_type,
            after=after,
            before=before,
            offset=offset,
            limit=limit,
        )

    @app.get("/config", dependencies=[Depends(require_read_api_key)])
    async def get_config() -> dict:
        return {
            "model.default_backend": runtime.config.get("model.default_backend"),
            "model.lmstudio.base_url": runtime.config.get("model.lmstudio.base_url"),
            "model.lmstudio.model": runtime.config.get("model.lmstudio.model"),
            "orchestrator.enable_subagents": runtime.config.get("orchestrator.enable_subagents"),
            "scheduler.heartbeat_timeout_s": runtime.config.get("scheduler.heartbeat_timeout_s"),
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

    @app.get("/skills/market", response_model=list[SkillMarketItem], dependencies=[Depends(require_read_api_key)])
    async def skills_market() -> list[SkillMarketItem]:
        return _current_market_rows()

    @app.post(
        "/skills/market/install",
        response_model=SkillMarketInstallResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def skills_market_install(body: SkillMarketInstallRequest) -> SkillMarketInstallResponse:
        skill_id = body.skill_id.strip()
        if skill_id not in market_registry:
            raise HTTPException(status_code=404, detail="Skill not found in local market registry")

        item = market_registry[skill_id]
        dependencies = [str(v) for v in list(item.get("dependencies", []))]
        missing_dependencies = sorted([dep for dep in dependencies if dep not in market_installed])
        missing_tools = sorted(_market_missing_tools(item))
        if missing_dependencies:
            raise HTTPException(
                status_code=400,
                detail=f"Missing skill dependencies: {', '.join(missing_dependencies)}",
            )
        if missing_tools:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required tools: {', '.join(missing_tools)}",
            )

        runtime.skills.register_skill(_market_to_skill_definition(item))
        market_installed.add(skill_id)
        _save_market_installed(market_installed)
        runtime.logger.log(
            "SKILL_MARKET_INSTALL",
            {
                "skill_id": skill_id,
                "version": str(item.get("version", "0.1.0")),
                "dependencies": dependencies,
                "required_tools": [str(v) for v in list(item.get("required_tools", []))],
            },
        )
        return SkillMarketInstallResponse(
            ok=True,
            skill_id=skill_id,
            installed=True,
            version=str(item.get("version", "0.1.0")),
        )

    @app.post(
        "/skills/market/uninstall",
        response_model=SkillMarketUninstallResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def skills_market_uninstall(body: SkillMarketUninstallRequest) -> SkillMarketUninstallResponse:
        skill_id = body.skill_id.strip()
        if skill_id not in market_installed:
            raise HTTPException(status_code=404, detail="Skill is not installed")

        dependents: list[str] = []
        for installed_id in sorted(market_installed):
            if installed_id == skill_id:
                continue
            item = market_registry.get(installed_id, {})
            deps = [str(v) for v in list(item.get("dependencies", []))]
            if skill_id in deps:
                dependents.append(installed_id)
        if dependents:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot uninstall; depended on by: {', '.join(dependents)}",
            )

        runtime.skills.unregister_skill(skill_id)
        market_installed.discard(skill_id)
        _save_market_installed(market_installed)
        runtime.logger.log(
            "SKILL_MARKET_UNINSTALL",
            {
                "skill_id": skill_id,
            },
        )
        return SkillMarketUninstallResponse(ok=True, skill_id=skill_id, uninstalled=True)

    @app.post(
        "/skills/market/update",
        response_model=SkillMarketUpdateResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def skills_market_update(body: SkillMarketUpdateRequest) -> SkillMarketUpdateResponse:
        skill_id = body.skill_id.strip()
        if skill_id not in market_registry:
            raise HTTPException(status_code=404, detail="Skill not found in local market registry")
        if skill_id not in market_installed:
            raise HTTPException(status_code=400, detail="Skill must be installed before update")

        item = market_registry[skill_id]
        missing_tools = sorted(_market_missing_tools(item))
        if missing_tools:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required tools: {', '.join(missing_tools)}",
            )

        runtime.skills.register_skill(_market_to_skill_definition(item))
        runtime.logger.log(
            "SKILL_MARKET_UPDATE",
            {
                "skill_id": skill_id,
                "version": str(item.get("version", "0.1.0")),
            },
        )
        return SkillMarketUpdateResponse(
            ok=True,
            skill_id=skill_id,
            updated=True,
            version=str(item.get("version", "0.1.0")),
        )

    @app.post(
        "/skills/market/remote/sync",
        response_model=SkillMarketRemoteSyncResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def skills_market_remote_sync(body: SkillMarketRemoteSyncRequest) -> SkillMarketRemoteSyncResponse:
        source = body.source.strip()
        now = datetime.now(timezone.utc)
        status = _load_market_remote_status()
        last_synced_at_raw = status.get("synced_at")
        if not body.force and isinstance(last_synced_at_raw, str):
            try:
                last_synced_at = datetime.fromisoformat(last_synced_at_raw)
            except ValueError:
                last_synced_at = None
            min_sync_seconds = int(runtime.config.get("skills.market_remote_min_sync_seconds", 0))
            if last_synced_at is not None and min_sync_seconds > 0:
                if (now - last_synced_at).total_seconds() < min_sync_seconds:
                    raise HTTPException(status_code=429, detail="Remote sync called too frequently; use force=true")

        try:
            loaded = await _fetch_remote_market_index(source)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Remote fetch failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Remote index is not valid JSON: {exc}") from exc

        signing_version = str(loaded.get("signing_version", "")).strip()
        index_hash = str(loaded.get("index_hash", "")).strip()
        source_from_index = str(loaded.get("source", source)).strip() or source
        generated_at = str(loaded.get("generated_at", "")).strip()
        items_raw = loaded.get("items", [])
        if signing_version not in {"v1", "v2-ed25519"}:
            raise HTTPException(status_code=400, detail="Unsupported remote index signing_version")
        if not isinstance(items_raw, list):
            raise HTTPException(status_code=400, detail="Remote index items must be a list")

        signature_payload = _market_signature_payload(
            source=source_from_index,
            generated_at=generated_at,
            signing_version=signing_version,
            items=items_raw,
        )
        computed_hash = _compute_report_hash_from_payload(signature_payload)

        if signing_version == "v2-ed25519":
            signature = str(loaded.get("signature", "")).strip()
            if not signature:
                raise HTTPException(status_code=400, detail="Missing remote index signature")

            cfg_keys = runtime.config.get("skills.market_trusted_public_keys", []) or []
            trusted_public_keys = [str(v) for v in cfg_keys if str(v).strip()]

            # Convenience for local testing: use embedded key if no pinned keys configured.
            if not trusted_public_keys and str(loaded.get("public_key", "")).strip():
                trusted_public_keys = [str(loaded.get("public_key", "")).strip()]

            if not trusted_public_keys:
                raise HTTPException(status_code=400, detail="No trusted public keys configured for remote sync")

            verified = _verify_ed25519_signature(
                signature_payload=signature_payload,
                signature_b64=signature,
                trusted_public_keys=trusted_public_keys,
            )
            if not verified:
                raise HTTPException(status_code=400, detail="Remote index signature verification failed")
        else:
            allow_v1_fallback = bool(runtime.config.get("skills.market_allow_v1_hash_fallback", True))
            if not allow_v1_fallback:
                raise HTTPException(status_code=400, detail="v1 hash-only market indexes are disabled")
            if not index_hash or index_hash != computed_hash:
                raise HTTPException(status_code=400, detail="Remote index v1 hash validation failed")

        effective_index_hash = index_hash or computed_hash

        normalized_items: list[dict[str, Any]] = []
        for candidate in items_raw:
            if not isinstance(candidate, dict):
                continue
            normalized = _normalize_market_item(candidate)
            if not normalized["skill_id"]:
                continue
            normalized_items.append(normalized)

        for item in normalized_items:
            market_registry[item["skill_id"]] = item
        _save_market_registry(market_registry)

        remote_cache_path = _market_remote_cache_path()
        remote_cache_path.parent.mkdir(parents=True, exist_ok=True)
        remote_cache_path.write_text(json.dumps(loaded, indent=2, sort_keys=True), encoding="utf-8")

        synced_at = now.isoformat()
        status_payload = {
            "source": source,
            "synced_at": synced_at,
            "pulled_count": len(normalized_items),
            "index_hash": effective_index_hash,
        }
        _save_market_remote_status(status_payload)
        runtime.logger.log(
            "SKILL_MARKET_REMOTE_SYNC",
            {
                "source": source,
                "pulled_count": len(normalized_items),
                "index_hash": effective_index_hash,
            },
        )

        return SkillMarketRemoteSyncResponse(
            ok=True,
            source=source,
            pulled_count=len(normalized_items),
            index_hash=effective_index_hash,
            synced_at=synced_at,
        )

    @app.get(
        "/skills/market/remote/status",
        response_model=SkillMarketRemoteStatusResponse,
        dependencies=[Depends(require_read_api_key)],
    )
    async def skills_market_remote_status() -> SkillMarketRemoteStatusResponse:
        return _current_market_remote_status()

    @app.get("/ui/market/overview", response_model=UiMarketOverviewResponse, dependencies=[Depends(require_read_api_key)])
    async def ui_market_overview() -> UiMarketOverviewResponse:
        rows = _current_market_rows()
        installed_count = sum(1 for r in rows if r.installed)
        installable_count = sum(1 for r in rows if (not r.installed and r.installable))
        non_installable_count = sum(1 for r in rows if (not r.installed and not r.installable))

        market_events: list[dict[str, Any]] = []
        for event_type in [
            "SKILL_MARKET_REMOTE_SYNC",
            "SKILL_MARKET_INSTALL",
            "SKILL_MARKET_UNINSTALL",
            "SKILL_MARKET_UPDATE",
        ]:
            market_events.extend(runtime.logger.query(event_type=event_type, limit=20))
        market_events.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
        recent_events = [LogEntry(**r) for r in market_events[:20]]

        return UiMarketOverviewResponse(
            total_listed=len(rows),
            installed_count=installed_count,
            installable_count=installable_count,
            non_installable_count=non_installable_count,
            remote_status=_current_market_remote_status(),
            recent_events=recent_events,
        )

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
        if bool(result.get("newly_missed_heartbeat", False)):
            await runtime.event_bus.publish(
                "MODULE_ERROR",
                {
                    "source": "scheduler.heartbeat",
                    "error": f"Missed heartbeat threshold exceeded ({result.get('heartbeat_lag_s')}s > {result.get('heartbeat_timeout_s')}s)",
                },
            )
        if bool(result.get("recovered_heartbeat", False)):
            runtime.logger.log(
                "SCHEDULER_HEARTBEAT_RECOVERED",
                {
                    "source": "scheduler",
                    "heartbeat_lag_s": result.get("heartbeat_lag_s"),
                },
            )
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

    @app.post(
        "/scheduler/maintenance/register",
        response_model=SchedulerMaintenanceRegisterResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def scheduler_register_maintenance_jobs() -> SchedulerMaintenanceRegisterResponse:
        registered = _register_maintenance_jobs()
        runtime.logger.log(
            "SCHEDULER_MAINTENANCE_REGISTERED",
            {
                "source": "api",
                "registered_jobs": registered,
            },
        )
        return SchedulerMaintenanceRegisterResponse(ok=True, registered_jobs=registered)

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

    @app.post("/reports/incident/export", response_model=IncidentReportExportResponse, dependencies=[Depends(require_admin_api_key)])
    async def incident_export(body: IncidentReportExportRequest) -> IncidentReportExportResponse:
        _validate_time_window(body.after, body.before)
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Export path blocked by execution policy")

        report = _build_incident_report(
            task_id=body.task_id,
            agent_id=body.agent_id,
            execution_id=body.execution_id,
            include_fix_executions=body.include_fix_executions,
            fix_event_type=body.fix_event_type,
            after=body.after,
            before=body.before,
            offset=body.offset,
            limit=body.limit,
        )
        payload = report.model_dump(mode="json")
        text = json.dumps(payload, indent=2, sort_keys=True)
        export_bytes = (text + "\n").encode("utf-8")
        max_export_bytes = int(runtime.config.get("reports.max_export_bytes", 262144))
        if len(export_bytes) > max_export_bytes:
            raise HTTPException(status_code=413, detail=f"Export payload exceeds limit ({len(export_bytes)} > {max_export_bytes})")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(export_bytes)
        runtime.logger.log("REPORT_EXPORTED", {"path": str(target), "report_hash": report.report_hash, "source": "api", "report_type": "incident"})
        return IncidentReportExportResponse(ok=True, path=str(target), bytes_written=len(export_bytes), report_hash=report.report_hash)

    @app.post("/diagnostics/emergency/export", response_model=EmergencyDiagnosisExportResponse, dependencies=[Depends(require_admin_api_key)])
    async def emergency_diagnosis_export(body: EmergencyDiagnosisExportRequest) -> EmergencyDiagnosisExportResponse:
        _validate_time_window(body.after, body.before)
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Export path blocked by execution policy")

        snapshot = _build_diagnosis_snapshot(
            source=body.source,
            agent_id=body.agent_id,
            skill_id=body.skill_id,
            after=body.after,
            before=body.before,
            offset=body.offset,
            limit=body.limit,
        )
        payload = snapshot.model_dump(mode="json")
        text = json.dumps(payload, indent=2, sort_keys=True)
        export_bytes = (text + "\n").encode("utf-8")
        max_export_bytes = int(runtime.config.get("reports.max_export_bytes", 262144))
        if len(export_bytes) > max_export_bytes:
            raise HTTPException(status_code=413, detail=f"Export payload exceeds limit ({len(export_bytes)} > {max_export_bytes})")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(export_bytes)
        runtime.logger.log("REPORT_EXPORTED", {"path": str(target), "report_hash": snapshot.report_hash, "source": "api", "report_type": "diagnosis_snapshot"})
        return EmergencyDiagnosisExportResponse(ok=True, path=str(target), bytes_written=len(export_bytes), report_hash=snapshot.report_hash)

    @app.post("/diagnostics/emergency/verify", response_model=EmergencyDiagnosisVerifyResponse, dependencies=[Depends(require_read_api_key)])
    async def emergency_diagnosis_verify(body: EmergencyDiagnosisVerifyRequest) -> EmergencyDiagnosisVerifyResponse:
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
        computed_hash = _compute_report_hash_from_payload(_signature_payload_from_diagnosis_snapshot(loaded))
        valid = stored_hash == computed_hash
        runtime.logger.log("REPORT_VERIFIED", {"path": str(target), "valid": valid, "stored_hash": stored_hash, "computed_hash": computed_hash, "source": "api", "report_type": "diagnosis_snapshot"})
        return EmergencyDiagnosisVerifyResponse(
            ok=True,
            path=str(target),
            valid=valid,
            stored_hash=stored_hash,
            computed_hash=computed_hash,
            signing_version=str(loaded.get("signing_version")) if loaded.get("signing_version") is not None else None,
        )

    @app.post(
        "/diagnostics/emergency/fix-executions/export",
        response_model=EmergencyFixExecutionExportResponse,
        dependencies=[Depends(require_admin_api_key)],
    )
    async def emergency_fix_execution_export(body: EmergencyFixExecutionExportRequest) -> EmergencyFixExecutionExportResponse:
        _validate_time_window(body.after, body.before)
        target = (workspace_root / body.path).resolve()
        if not runtime.execution.policy.is_cwd_allowed(target.parent):
            raise HTTPException(status_code=403, detail="Export path blocked by execution policy")

        snapshot = _build_fix_execution_snapshot(
            execution_id=body.execution_id,
            failure_id=body.failure_id,
            after=body.after,
            before=body.before,
            offset=body.offset,
            limit=body.limit,
        )
        payload = snapshot.model_dump(mode="json")
        text = json.dumps(payload, indent=2, sort_keys=True)
        export_bytes = (text + "\n").encode("utf-8")
        max_export_bytes = int(runtime.config.get("reports.max_export_bytes", 262144))
        if len(export_bytes) > max_export_bytes:
            raise HTTPException(status_code=413, detail=f"Export payload exceeds limit ({len(export_bytes)} > {max_export_bytes})")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(export_bytes)
        runtime.logger.log(
            "REPORT_EXPORTED",
            {
                "path": str(target),
                "report_hash": snapshot.report_hash,
                "source": "api",
                "report_type": "fix_execution_snapshot",
            },
        )
        return EmergencyFixExecutionExportResponse(
            ok=True,
            path=str(target),
            bytes_written=len(export_bytes),
            report_hash=snapshot.report_hash,
        )

    @app.post(
        "/diagnostics/emergency/fix-executions/verify",
        response_model=EmergencyFixExecutionVerifyResponse,
        dependencies=[Depends(require_read_api_key)],
    )
    async def emergency_fix_execution_verify(body: EmergencyFixExecutionVerifyRequest) -> EmergencyFixExecutionVerifyResponse:
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
        computed_hash = _compute_report_hash_from_payload(_signature_payload_from_fix_execution_snapshot(loaded))
        valid = stored_hash == computed_hash
        runtime.logger.log(
            "REPORT_VERIFIED",
            {
                "path": str(target),
                "valid": valid,
                "stored_hash": stored_hash,
                "computed_hash": computed_hash,
                "source": "api",
                "report_type": "fix_execution_snapshot",
            },
        )
        return EmergencyFixExecutionVerifyResponse(
            ok=True,
            path=str(target),
            valid=valid,
            stored_hash=stored_hash,
            computed_hash=computed_hash,
            signing_version=str(loaded.get("signing_version")) if loaded.get("signing_version") is not None else None,
        )

    @app.post("/reports/incident/verify", response_model=IncidentReportVerifyResponse, dependencies=[Depends(require_read_api_key)])
    async def incident_verify(body: IncidentReportVerifyRequest) -> IncidentReportVerifyResponse:
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
        computed_hash = _compute_report_hash_from_payload(_signature_payload_from_incident_report(loaded))
        valid = stored_hash == computed_hash
        runtime.logger.log("REPORT_VERIFIED", {"path": str(target), "valid": valid, "stored_hash": stored_hash, "computed_hash": computed_hash, "source": "api", "report_type": "incident"})
        return IncidentReportVerifyResponse(
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

    _INGESTION_STOPWORDS: frozenset[str] = frozenset({
        "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "a", "an",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "can", "with", "from", "by", "this", "that", "these", "those", "then",
        "when", "where", "how", "what", "which", "who", "not", "also", "more",
        "such", "if", "as", "it", "its", "into", "over", "after", "before",
        "about", "than", "other", "each", "their", "they", "we", "you",
    })

    def _concept_sequence_from_text(text: str) -> list[str]:
        """Return the filtered concept token sequence (with repeats) for frequency scoring."""
        tokens: list[str] = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)
        return [
            f"concept:{tok.lower()}"
            for tok in tokens
            if len(tok) >= 4 and tok.lower() not in _INGESTION_STOPWORDS
        ]

    def _extract_entities_relations(text: str) -> tuple[list[str], list[tuple[str, str]]]:
        """Return (unique node_ids, edge pairs) extracted from text using simple tokenization."""
        tokens: list[str] = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)
        concepts: list[str] = []
        for tok in tokens:
            normalized = tok.lower()
            if len(normalized) >= 4 and normalized not in _INGESTION_STOPWORDS:
                node_id = f"concept:{normalized}"
                concepts.append(node_id)

        # Deduplicate preserving first-seen order for node_ids list
        seen: set[str] = set()
        unique_nodes: list[str] = []
        for c in concepts:
            if c not in seen:
                seen.add(c)
                unique_nodes.append(c)

        # Co-occurrence edges between adjacent concept tokens (sliding window = 1)
        edge_set: set[tuple[str, str]] = set()
        for i in range(len(concepts) - 1):
            src, tgt = concepts[i], concepts[i + 1]
            if src != tgt:
                edge_set.add((src, tgt))

        return unique_nodes, list(edge_set)

    @app.post("/ingestion/graphify", response_model=GraphifyResponse, dependencies=[Depends(require_admin_api_key)])
    async def ingestion_graphify(body: GraphifyRequest) -> GraphifyResponse:
        confidence_min = float(runtime.config.get("ingestion.confidence_min", 0.0))

        node_ids, edges = _extract_entities_relations(body.text)

        # Build frequency map for confidence scoring
        all_concepts = _concept_sequence_from_text(body.text)
        total_occurrences = len(all_concepts)
        freq: dict[str, int] = {}
        for c in all_concepts:
            freq[c] = freq.get(c, 0) + 1

        nodes_added: list[str] = []
        nodes_skipped_count = 0

        for node_id in node_ids:
            confidence = freq.get(node_id, 1) / max(1, total_occurrences)

            # Confidence gate
            if confidence < confidence_min:
                nodes_skipped_count += 1
                runtime.logger.log(
                    "INGESTION_DEDUPE",
                    {
                        "node_id": node_id,
                        "reason": "below_confidence_threshold",
                        "confidence": round(confidence, 6),
                        "threshold": confidence_min,
                    },
                )
                continue

            # Exact deduplication — node already exists in graph
            if runtime.memory.graph_has_node(node_id):
                nodes_skipped_count += 1
                runtime.logger.log(
                    "INGESTION_DEDUPE",
                    {
                        "node_id": node_id,
                        "reason": "already_exists",
                        "confidence": round(confidence, 6),
                        "threshold": confidence_min,
                    },
                )
                continue

            concept_name = node_id.split(":", 1)[-1]
            props: dict[str, str] = {"text": concept_name}
            if body.metadata:
                props["source"] = str(body.metadata.get("source", ""))
            runtime.memory.graph_add_node(node_id, "concept", props)
            nodes_added.append(node_id)

        # Only add edges between nodes that are now in the graph (added or pre-existing)
        edges_added_count = 0
        edges_skipped_count = 0
        for src, tgt in edges:
            if runtime.memory.graph_has_edge(src, tgt):
                edges_skipped_count += 1
                continue
            # Both endpoints must exist in graph
            if runtime.memory.graph_has_node(src) and runtime.memory.graph_has_node(tgt):
                runtime.memory.graph_add_edge(src, tgt, "co_occurs")
                edges_added_count += 1

        runtime.logger.log(
            "INGESTION_COMPLETE",
            {
                "nodes_added": len(nodes_added),
                "nodes_skipped": nodes_skipped_count,
                "edges_added": edges_added_count,
                "edges_skipped": edges_skipped_count,
                "node_ids": nodes_added,
                "metadata": body.metadata,
            },
        )

        return GraphifyResponse(
            ok=True,
            nodes_added=len(nodes_added),
            nodes_skipped=nodes_skipped_count,
            edges_added=edges_added_count,
            edges_skipped=edges_skipped_count,
            node_ids=nodes_added,
        )

    @app.get("/ingestion/stats", response_model=IngestionStatsResponse, dependencies=[Depends(require_read_api_key)])
    async def ingestion_stats() -> IngestionStatsResponse:
        return _current_ingestion_stats()

    def _current_ingestion_stats() -> IngestionStatsResponse:
        rows = runtime.logger.query(event_type="INGESTION_COMPLETE", limit=10000)
        total_nodes = 0
        total_nodes_skipped = 0
        total_edges = 0
        total_edges_skipped = 0
        last_at: str | None = None
        for row in rows:
            payload = row.get("payload", {}) if isinstance(row.get("payload", {}), dict) else {}
            total_nodes += int(payload.get("nodes_added", 0))
            total_nodes_skipped += int(payload.get("nodes_skipped", 0))
            total_edges += int(payload.get("edges_added", 0))
            total_edges_skipped += int(payload.get("edges_skipped", 0))
            ts = row.get("timestamp")
            if ts and (last_at is None or ts > last_at):
                last_at = str(ts)
        return IngestionStatsResponse(
            total_ingestions=len(rows),
            total_nodes_added=total_nodes,
            total_nodes_skipped=total_nodes_skipped,
            total_edges_added=total_edges,
            total_edges_skipped=total_edges_skipped,
            last_ingested_at=last_at,
        )

    @app.get("/ui/ingestion/overview", response_model=UiIngestionOverviewResponse, dependencies=[Depends(require_read_api_key)])
    async def ui_ingestion_overview() -> UiIngestionOverviewResponse:
        ingestion_rows = runtime.logger.query(event_type="INGESTION_COMPLETE", limit=20)
        recent_ingestions = [LogEntry(**r) for r in ingestion_rows]

        dedupe_rows = runtime.logger.query(event_type="INGESTION_DEDUPE", limit=20)
        recent_dedupe_entries = [
            IngestionDedupeEntry(
                timestamp=str(r.get("timestamp", "")),
                node_id=str(dict(r.get("payload", {})).get("node_id", "")),
                reason=str(dict(r.get("payload", {})).get("reason", "")),
                confidence=float(dict(r.get("payload", {})).get("confidence", 0.0)),
                threshold=float(dict(r.get("payload", {})).get("threshold", 0.0)),
            )
            for r in dedupe_rows
        ]

        return UiIngestionOverviewResponse(
            stats=_current_ingestion_stats(),
            recent_ingestions=recent_ingestions,
            recent_dedupe_events=recent_dedupe_entries,
        )

    @app.get("/ingestion/dedupe-log", response_model=IngestionDedupeLogResponse, dependencies=[Depends(require_read_api_key)])
    async def ingestion_dedupe_log(
        node_id: str | None = None,
        reason: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> IngestionDedupeLogResponse:
        clamped_limit = max(1, min(limit, 500))
        clamped_offset = max(0, offset)
        rows = runtime.logger.query(event_type="INGESTION_DEDUPE", limit=10000)

        entries: list[IngestionDedupeEntry] = []
        for row in rows:
            payload = row.get("payload", {}) if isinstance(row.get("payload", {}), dict) else {}
            if node_id and payload.get("node_id") != node_id:
                continue
            if reason and payload.get("reason") != reason:
                continue
            entries.append(
                IngestionDedupeEntry(
                    timestamp=str(row.get("timestamp", "")),
                    node_id=str(payload.get("node_id", "")),
                    reason=str(payload.get("reason", "")),
                    confidence=float(payload.get("confidence", 0.0)),
                    threshold=float(payload.get("threshold", 0.0)),
                )
            )

        paginated, has_more, next_offset = _paginate(entries, offset=clamped_offset, limit=clamped_limit)
        return IngestionDedupeLogResponse(
            items=paginated,
            limit=clamped_limit,
            offset=clamped_offset,
            has_more=has_more,
            next_offset=next_offset,
        )

    return app


