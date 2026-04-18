from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from harness.runtime.bootstrap import RuntimeContext

SEVERITY_PENALTIES: dict[str, int] = {
    "critical": 25,
    "error": 15,
    "warning": 5,
    "info": 0,
}

CRITICAL_RELIABILITY_PENALTY = 20
ALL_CATEGORIES: tuple[str, ...] = ("config", "auth", "tools", "memory", "eval", "scale")


def run_audit(
    runtime: RuntimeContext,
    *,
    workspace_root: Path,
    key_store: Any | None = None,
    run_queue: Any | None = None,
    categories: set[str] | None = None,
) -> dict[str, Any]:
    selected = [name for name in ALL_CATEGORIES if categories is None or name in categories]
    health_records = {record["name"]: record for record in runtime.health.as_list()}

    category_reports: dict[str, dict[str, Any]] = {}
    for name in selected:
        findings = _run_category(
            name,
            runtime=runtime,
            workspace_root=workspace_root,
            key_store=key_store,
            run_queue=run_queue,
            health_records=health_records,
        )
        category_reports[name] = {
            "score": _score_findings(findings),
            "findings": findings,
        }

    category_scores = [int(report["score"]) for report in category_reports.values()] or [100]
    critical_count = sum(
        1
        for report in category_reports.values()
        for finding in report["findings"]
        if finding["severity"] == "critical"
    )
    reliability_score = max(0, min(100, int(round(mean(category_scores) - critical_count * CRITICAL_RELIABILITY_PENALTY))))

    eval_findings = category_reports.get("eval", {"findings": []})["findings"]
    eval_readiness = _eval_readiness(eval_findings)
    risk_level = _risk_level(reliability_score)

    return {
        "audit_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "harness_version": _resolve_harness_version(workspace_root),
        "reliability_score": reliability_score,
        "eval_readiness": eval_readiness,
        "risk_level": risk_level,
        "categories": category_reports,
        "summary": _build_summary(reliability_score, eval_readiness, risk_level, category_reports),
    }


def render_audit_text(report: dict[str, Any]) -> str:
    lines = [
        f"TitanShift Harness Audit v{report['audit_version']}",
        f"Generated: {report['generated_at']}",
        f"Harness version: {report['harness_version']}",
        f"Reliability score: {report['reliability_score']}",
        f"Eval readiness: {report['eval_readiness']}",
        f"Risk level: {report['risk_level']}",
        "",
        report["summary"],
    ]
    for name, category in report["categories"].items():
        lines.extend(["", f"[{name}] score={category['score']}"])
        findings = category.get("findings", [])
        if not findings:
            lines.append("- no findings")
            continue
        for finding in findings:
            lines.append(f"- {finding['id']} {finding['severity']}: {finding['title']}")
            lines.append(f"  {finding['detail']}")
            lines.append(f"  remediation: {finding['remediation']}")
    return "\n".join(lines)


def _run_category(
    name: str,
    *,
    runtime: RuntimeContext,
    workspace_root: Path,
    key_store: Any | None,
    run_queue: Any | None,
    health_records: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    if name == "config":
        return _config_findings(runtime, workspace_root)
    if name == "auth":
        return _auth_findings(runtime, key_store)
    if name == "tools":
        return _tool_findings(runtime)
    if name == "memory":
        return _memory_findings(runtime, workspace_root, health_records)
    if name == "eval":
        return _eval_findings(runtime, workspace_root)
    if name == "scale":
        return _scale_findings(runtime, run_queue)
    raise ValueError(f"Unknown audit category: {name}")


def _config_findings(runtime: RuntimeContext, workspace_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cfg = runtime.config
    require_api_key = bool(cfg.get("api.require_api_key", False))
    require_admin = bool(cfg.get("api.require_admin_api_key", False))
    if not require_api_key:
        findings.append(
            _finding(
                "AUDIT-C001",
                "warning",
                "Read API key enforcement disabled",
                "api.require_api_key is false. If this harness is reachable beyond localhost, unauthenticated reads are possible.",
                "Enable api.require_api_key or restrict network exposure to localhost/private ingress.",
            )
        )
    if require_api_key and not str(cfg.get("api.api_key", "")).strip():
        findings.append(
            _finding(
                "AUDIT-C002",
                "error",
                "Missing configured read API key",
                "api.require_api_key is true but api.api_key is empty.",
                "Configure api.api_key or disable the requirement until managed keys are in place.",
            )
        )
    if require_admin and not str(cfg.get("api.admin_api_key", "")).strip():
        findings.append(
            _finding(
                "AUDIT-C003",
                "error",
                "Missing configured admin API key",
                "api.require_admin_api_key is true but api.admin_api_key is empty.",
                "Configure api.admin_api_key before enabling admin enforcement.",
            )
        )
    if str(cfg.get("model.default_backend", "")).strip().lower() == "local_stub":
        findings.append(
            _finding(
                "AUDIT-C004",
                "warning",
                "Stub model backend is the default",
                "model.default_backend is local_stub, which is appropriate for local smoke tests but not production behavior.",
                "Set model.default_backend to a real model adapter for production-like runs.",
            )
        )
    if int(cfg.get("execution.run_timeout_seconds", 300) or 0) == 0:
        findings.append(
            _finding(
                "AUDIT-C005",
                "warning",
                "Run timeout is unbounded",
                "execution.run_timeout_seconds is 0, so queued runs can execute indefinitely.",
                "Set a bounded execution.run_timeout_seconds value.",
            )
        )
    if int(cfg.get("execution.max_concurrent_runs", 4) or 0) > 20:
        findings.append(
            _finding(
                "AUDIT-C006",
                "warning",
                "Concurrent run ceiling is high",
                "execution.max_concurrent_runs exceeds 20, which raises contention risk for model and storage backends.",
                "Lower execution.max_concurrent_runs or verify backend capacity under load.",
            )
        )
    storage_dir = workspace_root / str(cfg.get("memory.storage_dir", ".harness"))
    writable_target = storage_dir if storage_dir.exists() else storage_dir.parent
    if not writable_target.exists() or not writable_target.is_dir() or not os_access_write(writable_target):
        findings.append(
            _finding(
                "AUDIT-C007",
                "error",
                "Memory storage directory is not writable",
                f"The memory storage path {storage_dir} is not writable by the current process.",
                "Fix directory permissions or point memory.storage_dir at a writable location.",
            )
        )
    if not bool(cfg.get("reports.redact_by_default", True)):
        findings.append(
            _finding(
                "AUDIT-C008",
                "warning",
                "Report redaction is disabled by default",
                "reports.redact_by_default is false, increasing the chance of sensitive data leakage in exports.",
                "Enable reports.redact_by_default unless an explicit review flow requires raw exports.",
            )
        )
    return findings


def _auth_findings(runtime: RuntimeContext, key_store: Any | None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cfg = runtime.config
    keys = key_store.list_keys() if key_store is not None else []
    active_keys = [record for record in keys if getattr(record, "is_active", False)]
    admin_keys = [record for record in active_keys if getattr(record, "is_admin", False)]
    operator_keys = [record for record in active_keys if getattr(record, "is_operator", False)]
    if not active_keys and not bool(cfg.get("api.require_api_key", False)):
        findings.append(
            _finding(
                "AUDIT-A001",
                "info",
                "No active managed API keys",
                "The key store contains no active keys while api.require_api_key is disabled.",
                "Create scoped managed keys before exposing the service to other operators.",
            )
        )
    if any(getattr(record, "expires_at", None) is None for record in admin_keys):
        findings.append(
            _finding(
                "AUDIT-A002",
                "warning",
                "Admin keys do not expire",
                "At least one active admin-scoped key has no expires_at value.",
                "Rotate long-lived admin keys and set explicit expirations.",
            )
        )
    if any(str(getattr(record, "tenant_id", "")).strip() == "_system_" for record in active_keys):
        findings.append(
            _finding(
                "AUDIT-A003",
                "info",
                "System-tenant keys are present",
                "At least one active key uses the _system_ tenant and bypasses tenant isolation boundaries.",
                "Reserve _system_ keys for bootstrap/admin flows only and prefer tenant-scoped keys.",
            )
        )
    if operator_keys and all(not list(getattr(record, "allowed_tools", []) or []) for record in operator_keys):
        findings.append(
            _finding(
                "AUDIT-A004",
                "info",
                "Operator keys rely on broad tool defaults",
                "All active operator-scoped keys have empty allowed_tools lists.",
                "Assign tenant-level allowed_tools lists if you want explicit per-key tool narrowing.",
            )
        )
    if len(admin_keys) > 10:
        findings.append(
            _finding(
                "AUDIT-A005",
                "warning",
                "High admin key count",
                f"There are {len(admin_keys)} active admin-scoped keys in the key store.",
                "Reduce active admin keys and rotate unused credentials.",
            )
        )
    return findings


def _tool_findings(runtime: RuntimeContext) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    tools = runtime.tools.list_tools()
    policy = runtime.tools.policy
    if not policy.deny_all_by_default and not policy.allowed_tool_names:
        findings.append(
            _finding(
                "AUDIT-T001",
                "warning",
                "Tool policy defaults open",
                "tools.deny_all_by_default is false and there is no explicit allow-list.",
                "Enable deny-all-by-default or define an explicit allowed_tool_names set.",
            )
        )
    shell_tools = {"bash_eval", "run_tests"}
    if any(tool.name in shell_tools for tool in tools) and not runtime.execution.policy.allowed_command_prefixes:
        findings.append(
            _finding(
                "AUDIT-T002",
                "warning",
                "Shell-capable tools lack execution policy prefixes",
                "Shell-execution tools are registered but execution.allowed_command_prefixes is empty.",
                "Set execution.allowed_command_prefixes to the minimum approved command set.",
            )
        )
    officecli_tools = [tool for tool in tools if tool.name.startswith("officecli_")]
    if officecli_tools and shutil.which("officecli") is None:
        findings.append(
            _finding(
                "AUDIT-T003",
                "info",
                "OfficeCLI tools are registered without the binary",
                "officecli tools are available in the registry but the officecli executable is not on PATH.",
                "Install officecli or unregister those tools for this deployment.",
            )
        )
    if len(tools) > 50:
        findings.append(
            _finding(
                "AUDIT-T004",
                "warning",
                "Large tool surface",
                f"{len(tools)} tools are registered, which can degrade LLM routing and schema size.",
                "Hide or scope infrequently used tools for production runs.",
            )
        )
    missing_commands = sorted(
        {
            command
            for tool in tools
            for command in tool.required_commands
            if shutil.which(command) is None
        }
    )
    if missing_commands:
        findings.append(
            _finding(
                "AUDIT-T005",
                "warning",
                "Registered tools have missing required commands",
                f"Required commands not found on PATH: {', '.join(missing_commands)}.",
                "Install the missing binaries or unregister the dependent tools.",
            )
        )
    return findings


def _memory_findings(
    runtime: RuntimeContext,
    workspace_root: Path,
    health_records: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cfg = runtime.config
    if runtime.memory.graph_backend_name == "networkx":
        findings.append(
            _finding(
                "AUDIT-M001",
                "info",
                "Graph backend is local networkx",
                "memory.graph_backend resolved to networkx, so graph state persists locally and is not multi-process durable.",
                "Use the Neo4j backend if shared persistent graph state is required.",
            )
        )
    storage_dir = workspace_root / str(cfg.get("memory.storage_dir", ".harness"))
    size_bytes = _directory_size_bytes(storage_dir)
    if size_bytes > 5 * 1024 * 1024 * 1024:
        findings.append(
            _finding(
                "AUDIT-M002",
                "warning",
                "Storage directory exceeds 5 GB",
                f"memory.storage_dir currently uses {size_bytes} bytes.",
                "Trim old artifacts/logs or move storage to a larger dedicated volume.",
            )
        )
    semantic_backend = str(cfg.get("memory.semantic_backend", "sqlite")).strip().lower()
    semantic_store = getattr(runtime.memory, "semantic", None)
    if semantic_backend in {"chroma", "sqlite"} and semantic_store is None:
        findings.append(
            _finding(
                "AUDIT-M003",
                "warning",
                "Semantic backend is not initialized",
                f"memory.semantic_backend is {semantic_backend} but no semantic store instance is attached.",
                "Initialize the semantic backend during runtime bootstrap.",
            )
        )
    elif semantic_backend == "sqlite":
        db_path = getattr(semantic_store, "db_path", None)
        if db_path is not None and not Path(db_path).exists():
            findings.append(
                _finding(
                    "AUDIT-M003",
                    "warning",
                    "Semantic SQLite store is missing on disk",
                    f"The semantic store database {db_path} does not exist.",
                    "Reinitialize the semantic store or repair the storage volume.",
                )
            )
        elif semantic_backend == "chroma" and not bool(cfg.get("memory.enable_chroma", False)):
            findings.append(
                _finding(
                    "AUDIT-M003",
                    "warning",
                    "Chroma semantic backend is disabled",
                    "memory.semantic_backend is chroma but memory.enable_chroma is false.",
                    "Enable chroma support or switch memory.semantic_backend back to sqlite.",
                )
            )
        
    memory_details = dict(health_records.get("memory", {}).get("details", {}) or {})
    write_latency_ms = float(memory_details.get("write_latency_ms", 0) or 0)
    if write_latency_ms > 500:
        findings.append(
            _finding(
                "AUDIT-M004",
                "warning",
                "Memory write latency is elevated",
                f"Last recorded memory write latency was {write_latency_ms:.1f} ms.",
                "Inspect storage contention and semantic backend latency.",
            )
        )
    return findings


def _eval_findings(runtime: RuntimeContext, workspace_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cfg = runtime.config
    if str(cfg.get("model.default_backend", "")).strip().lower() == "local_stub":
        findings.append(
            _finding(
                "AUDIT-E001",
                "critical",
                "Eval backend is still local_stub",
                "model.default_backend is local_stub, so evaluations cannot measure real model behavior.",
                "Switch model.default_backend to a real adapter before running evals.",
            )
        )
    if not (workspace_root / "tests" / "test_smoke.py").exists():
        findings.append(
            _finding(
                "AUDIT-E002",
                "warning",
                "Smoke test file is missing",
                "tests/test_smoke.py was not found in the workspace.",
                "Restore or add a smoke test suite for baseline eval verification.",
            )
        )
    lastfailed_path = workspace_root / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if lastfailed_path.exists():
        try:
            lastfailed = json.loads(lastfailed_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            lastfailed = {}
        if isinstance(lastfailed, dict) and lastfailed:
            findings.append(
                _finding(
                    "AUDIT-E003",
                    "error",
                    "Last pytest run recorded failures",
                    f".pytest_cache/v/cache/lastfailed contains {len(lastfailed)} failing test entries.",
                    "Re-run the test suite and clear the recorded failures before declaring eval readiness.",
                )
            )
    if float(cfg.get("orchestrator.skill_execution_timeout_s", 15.0) or 0) < 5:
        findings.append(
            _finding(
                "AUDIT-E004",
                "warning",
                "Skill execution timeout is too low",
                "orchestrator.skill_execution_timeout_s is below 5 seconds, which can truncate reproducible runs.",
                "Raise orchestrator.skill_execution_timeout_s to at least 5 seconds.",
            )
        )
    if int(cfg.get("reports.max_export_bytes", 262144) or 0) < 65536:
        findings.append(
            _finding(
                "AUDIT-E005",
                "warning",
                "Export byte ceiling is small",
                "reports.max_export_bytes is below 65536, which may truncate reproducible reports.",
                "Increase reports.max_export_bytes for evaluation/reporting workloads.",
            )
        )
    return findings


def _scale_findings(runtime: RuntimeContext, run_queue: Any | None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cfg = runtime.config
    if int(cfg.get("execution.max_concurrent_runs", 4) or 0) == 1:
        findings.append(
            _finding(
                "AUDIT-S001",
                "info",
                "Run queue is single-threaded",
                "execution.max_concurrent_runs is 1, so the harness cannot process runs in parallel.",
                "Increase execution.max_concurrent_runs if the backing model and storage layers can support it.",
            )
        )
    task_store_conn = getattr(runtime.orchestrator.task_store, "_conn", None)
    if task_store_conn is not None:
        journal_mode = str(task_store_conn.execute("PRAGMA journal_mode").fetchone()[0]).upper()
        if journal_mode != "WAL":
            findings.append(
                _finding(
                    "AUDIT-S002",
                    "warning",
                    "Task store is not using WAL mode",
                    f"Task-store SQLite journal_mode is {journal_mode}.",
                    "Enable WAL on the task store to reduce reader/writer contention.",
                )
            )
    if run_queue is None or not hasattr(run_queue, "retry_after_seconds"):
        findings.append(
            _finding(
                "AUDIT-S003",
                "info",
                "Retry-After guidance is unavailable",
                "The run queue does not expose Retry-After guidance for capacity throttling.",
                "Wire queue-derived Retry-After values into 429 responses.",
            )
        )
    if int(cfg.get("execution.run_timeout_seconds", 300) or 0) < 30:
        findings.append(
            _finding(
                "AUDIT-S004",
                "warning",
                "Run timeout is aggressive for scale",
                "execution.run_timeout_seconds is below 30 seconds.",
                "Raise execution.run_timeout_seconds if legitimate workloads are timing out under load.",
            )
        )
    return findings


def _finding(identifier: str, severity: str, title: str, detail: str, remediation: str) -> dict[str, str]:
    return {
        "id": identifier,
        "severity": severity,
        "title": title,
        "detail": detail,
        "remediation": remediation,
    }


def _score_findings(findings: list[dict[str, str]]) -> int:
    score = 100
    for finding in findings:
        score -= SEVERITY_PENALTIES.get(finding["severity"], 0)
    return max(0, min(100, score))


def _eval_readiness(findings: list[dict[str, str]]) -> str:
    severities = {finding["severity"] for finding in findings}
    if "critical" in severities or "error" in severities:
        return "not_ready"
    if "warning" in severities:
        return "partial"
    return "ready"


def _risk_level(score: int) -> str:
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


def _build_summary(
    reliability_score: int,
    eval_readiness: str,
    risk_level: str,
    categories: dict[str, dict[str, Any]],
) -> str:
    open_findings = sum(len(category.get("findings", [])) for category in categories.values())
    weakest_category = min(categories.items(), key=lambda item: item[1]["score"])[0] if categories else "config"
    return (
        f"Harness reliability is {reliability_score}/100 with {risk_level} operational risk. "
        f"Eval readiness is {eval_readiness}. "
        f"The weakest category is {weakest_category}, and {open_findings} audit findings are currently open."
    )


def _resolve_harness_version(workspace_root: Path) -> str:
    pyproject = workspace_root / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version ="):
            return stripped.split("=", 1)[1].strip().strip('"')
    return "unknown"


def _directory_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def os_access_write(path: Path) -> bool:
    import os

    return os.access(path, os.W_OK)