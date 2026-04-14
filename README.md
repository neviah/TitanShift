# TitantShift Universal Harness (Phase 1 + Phase 2)

Python-first, modular, local-first harness scaffold.

## Included in this scaffold

- Runtime core: module loader, config manager, event bus.
- Model module: local stub + cloud adapter stub.
- Tool module: deny-all default permission policy.
- Memory module:
  - Working, short-term, long-term in manager.
  - Semantic storage via SQLite FTS + embeddings table.
  - Graph backend adapter defaulting to NetworkX.
- State machine: reactive single-agent loop.
- Orchestrator: reactive path, sub-agent spawning, agent skill assignment, and agent-scoped skill execution.
- Execution, emergency, scheduler, API hooks, graphify plugin stubs.
- CLI entrypoint runnable via python -m harness.

## Design decisions applied from your constraints

- Cloud model adapters exist but are optional.
- NetworkX-first graph backend behind adapter.
- SQLite semantic default; Chroma behind feature flag/stub.
- Graphify integrated as optional ingestion plugin.
- Custom memory engine inspired by MemPalace patterns.
- CLI-first MVP with API hook surface for future UI.
- Sub-agent spawning and agent skill execution stay behind runtime policy/config.
- Tool execution deny-all by default.

## Quick start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Print runtime status:

```bash
python -m harness --workspace . status
```

4. Run a simple reactive task:

```bash
python -m harness --workspace . run-task "Summarize current harness mode"
```

5. Run a task against LM Studio (requires local server running):

```bash
python -m harness --workspace . run-task "Explain this codebase briefly" --backend lmstudio
```

6. Start API server:

```bash
python -m harness --workspace . serve-api --host 127.0.0.1 --port 8000
```

Then call:

```bash
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"prompt\":\"hello\",\"model_backend\":\"local_stub\"}"
```

Per-request budget override example:

```bash
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"prompt\":\"large task\",\"model_backend\":\"lmstudio\",\"budget\":{\"max_tokens\":16000,\"max_duration_ms\":120000}}"
```

`/chat` now returns `success`, optional `error`, and `estimated_total_tokens`.

Task history endpoints:

```bash
curl http://127.0.0.1:8000/tasks
curl http://127.0.0.1:8000/tasks/<task_id>
```

Logs endpoint (with filters):

```bash
curl "http://127.0.0.1:8000/logs?limit=100"
curl "http://127.0.0.1:8000/logs?event_type=MODULE_ERROR&limit=20"
curl "http://127.0.0.1:8000/logs?task_id=<task_id>"
curl "http://127.0.0.1:8000/logs?agent_id=<agent_id>&skill_id=<skill_id>&limit=20"
curl "http://127.0.0.1:8000/logs?event_type=AGENT_SKILL_EXECUTED&offset=20&limit=20"
curl "http://127.0.0.1:8000/logs?after=2026-04-10T00:00:00%2B00:00&before=2026-04-10T23:59:59%2B00:00&limit=50"
```

`/logs` now supports `agent_id`, `skill_id`, `execution_id`, `after`, `before`, and `offset` for incident pagination.
The response now includes `items`, `limit`, `offset`, `has_more`, and `next_offset`.

Runtime config API (in-memory override for current process):

```bash
curl http://127.0.0.1:8000/config
curl -X POST http://127.0.0.1:8000/config -H "Content-Type: application/json" -d "{\"key\":\"state_machine.default_budget.max_tokens\",\"value\":16000}"
```

Scheduler API (idle by default, explicit triggers only):

```bash
curl http://127.0.0.1:8000/scheduler/jobs
curl -X POST http://127.0.0.1:8000/scheduler/maintenance/register
curl -X POST http://127.0.0.1:8000/scheduler/heartbeat
curl -X POST http://127.0.0.1:8000/scheduler/tick
curl -X POST http://127.0.0.1:8000/scheduler/jobs/scheduler_heartbeat/enabled -H "Content-Type: application/json" -d "{\"enabled\":false}"
```

Scheduler job rows now include `max_failures`, `failure_count`, and `last_error`.
Scheduler job rows also include `timeout_s`, `schedule_type`, and optional `cron`.
Ticks report `failed_jobs`, `timed_out_jobs`, and `auto_disabled_jobs` so repeated failures and hung jobs can be detected.
Ticks now also surface heartbeat telemetry: `missed_heartbeat`, `newly_missed_heartbeat`, `recovered_heartbeat`, `heartbeat_lag_s`, and `heartbeat_timeout_s`.
When a missed heartbeat is first detected, the API escalates through Emergency and records `EMERGENCY_DIAGNOSIS` and `EMERGENCY_FIX_PLAN` events for `scheduler.heartbeat`.
Use `/scheduler/maintenance/register` to install default non-destructive maintenance jobs (`maintenance_health_snapshot`, `maintenance_retention_preview`).

Agents visibility API:

```bash
curl http://127.0.0.1:8000/agents
```

Agent orchestration API:

```bash
curl -X POST http://127.0.0.1:8000/agents/spawn -H "Content-Type: application/json" -d "{\"description\":\"Need shell execution support\",\"role\":\"Execution Specialist\"}"
curl -X POST http://127.0.0.1:8000/agents/<agent_id>/skills/assign -H "Content-Type: application/json" -d "{\"skill_ids\":[\"safe_shell_command\"]}"
curl -X POST http://127.0.0.1:8000/agents/<agent_id>/skills/safe_shell_command/execute -H "Content-Type: application/json" -d "{\"input\":{\"command\":\"python --version\"}}"
```

Agent-scoped skill execution returns an `execution_id` and emits an `AGENT_SKILL_EXECUTED` log event.
If the skill is not assigned to that agent, the API returns `403`.
If execution exceeds the configured timeout, the API returns `504`.

Skills and tools API:

```bash
curl http://127.0.0.1:8000/skills
curl "http://127.0.0.1:8000/skills?query=shell"
curl "http://127.0.0.1:8000/skills?tags=safety"
curl "http://127.0.0.1:8000/skills?related_node_id=tool:shell_command"
curl -X POST http://127.0.0.1:8000/skills/reactive_chat/execute -H "Content-Type: application/json" -d "{\"input\":{\"message\":\"hello\"}}"
curl http://127.0.0.1:8000/skills/market
curl -X POST http://127.0.0.1:8000/skills/market/install -H "Content-Type: application/json" -d "{\"skill_id\":\"web-search-basic\"}"
curl -X POST http://127.0.0.1:8000/skills/market/update -H "Content-Type: application/json" -d "{\"skill_id\":\"web-search-basic\"}"
curl -X POST http://127.0.0.1:8000/skills/market/uninstall -H "Content-Type: application/json" -d "{\"skill_id\":\"web-search-basic\"}"
curl -X POST http://127.0.0.1:8000/skills/market/remote/sync -H "Content-Type: application/json" -d "{\"source\":\"https://raw.githubusercontent.com/neviah/titanshift_marketplace_index/main/market/index.json\",\"force\":true}"
curl -X POST http://127.0.0.1:8000/skills/repo-intake -H "Content-Type: application/json" -d "{\"repo_url\":\"https://github.com/jo-inc/camofox-browser\",\"auto_install\":true}"
curl http://127.0.0.1:8000/skills/market/remote/status
curl http://127.0.0.1:8000/ui/market/overview
curl http://127.0.0.1:8000/ui/ingestion/overview
curl http://127.0.0.1:8000/tools
curl "http://127.0.0.1:8000/tools?query=shell"
```

`/skills` now returns `mode`, `domain`, `version`, and `ranking_score`.
Ranking favors direct query hits, tag overlap, and graph-linked tool overlap from `related_node_id`.
`/skills/market` returns installability flags and dependency/tool gaps for each listed skill.
`/skills/market/remote/sync` validates remote index signatures and caches sync status.
`/skills/repo-intake` classifies a repo link and can auto-install a local integration skill wrapper.
`/ui/market/overview` and `/ui/ingestion/overview` are UI-oriented summary endpoints for dashboard cards.

Read-only memory inspect API:

```bash
curl http://127.0.0.1:8000/memory/summary
curl "http://127.0.0.1:8000/memory/semantic-search?query=alpha&limit=5"
curl "http://127.0.0.1:8000/memory/graph/neighbors?node_id=n1"
curl "http://127.0.0.1:8000/memory/graph/search?query=shell&node_type=skill&limit=10"
curl -X POST http://127.0.0.1:8000/memory/graph/migration/export -H "Content-Type: application/json" -d "{\"backend\":\"local\",\"path\":\".harness/graph_snapshot.json\"}"
curl -X POST http://127.0.0.1:8000/memory/graph/migration/import -H "Content-Type: application/json" -d "{\"backend\":\"local\",\"path\":\".harness/graph_snapshot.json\",\"clear_existing\":true}"
```

Graph migration endpoints support `backend=local` and `backend=neo4j`.
For Neo4j migration, provide `neo4j_uri`, `neo4j_username`, `neo4j_password` (and optional `neo4j_database`) in the request body, or set `memory.neo4j.*` config keys.

Emergency diagnostics API:

```bash
curl "http://127.0.0.1:8000/diagnostics/emergency?limit=20"
curl "http://127.0.0.1:8000/diagnostics/emergency?source=orchestrator.skill_execution&limit=20"
curl "http://127.0.0.1:8000/diagnostics/emergency?agent_id=<agent_id>&skill_id=<skill_id>&limit=20"
curl "http://127.0.0.1:8000/diagnostics/emergency?offset=20&limit=20"
curl "http://127.0.0.1:8000/diagnostics/emergency?after=2026-04-10T00:00:00%2B00:00&before=2026-04-10T23:59:59%2B00:00&limit=50"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/analyze -H "Content-Type: application/json" -d "{\"source\":\"orchestrator.skill_execution\",\"error\":\"Timed out after 15.0s\",\"agent_id\":\"<agent_id>\",\"skill_id\":\"<skill_id>\",\"context\":{\"task_id\":\"<task_id>\"}}"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/fix-apply -H "Content-Type: application/json" -d "{\"approved\":true,\"dry_run\":true,\"fix_plan\":{\"failure_id\":\"failure-123\",\"recommended_hypothesis\":\"Execution budget exceeded\",\"risk_level\":\"medium\",\"requires_user_approval\":true,\"actions\":[{\"action_type\":\"update_config\",\"params\":{\"key\":\"orchestrator.skill_execution_timeout_s\",\"value\":30.0}}],\"notes\":\"Review before apply\"}}"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/fix-rollback -H "Content-Type: application/json" -d "{\"execution_id\":\"fix-abc123\",\"dry_run\":true}"
curl "http://127.0.0.1:8000/diagnostics/emergency/fix-executions?execution_id=fix-abc123&limit=20"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/fix-executions/export -H "Content-Type: application/json" -d "{\"path\":\".harness/fix-executions.json\",\"execution_id\":\"fix-abc123\",\"limit\":50}"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/fix-executions/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/fix-executions.json\"}"
```

Each diagnosis entry includes `timestamp`, `source`, optional `agent_id`, optional `skill_id`, and structured diagnosis suggestions.
The response now includes `items`, `limit`, `offset`, `has_more`, and `next_offset`.
`/diagnostics/emergency/analyze` returns a `failure_id`, ranked diagnoses, and a proposed fix plan.
`/diagnostics/emergency/fix-apply` requires explicit `approved=true`; keep `dry_run=true` to preview actions safely.
Analyze responses include `selected_hypothesis` and `consensus` entries (`confidence_avg`, `source_weight`, `vote_count`, `consensus_score`) for traceability.
Successful non-dry-run fix application returns `execution_id` and `rollback_available` metadata.
`/diagnostics/emergency/fix-rollback` replays rollback actions for a prior fix execution when available.
`/diagnostics/emergency/fix-executions` provides paginated apply/rollback event history filtered by `execution_id`, `failure_id`, and time windows.
Fix execution snapshots support signed export and verification through `/diagnostics/emergency/fix-executions/export` and `/diagnostics/emergency/fix-executions/verify`.

Incident report API:

```bash
curl "http://127.0.0.1:8000/reports/incident?agent_id=<agent_id>&limit=50"
curl "http://127.0.0.1:8000/reports/incident?task_id=<task_id>&limit=50"
curl "http://127.0.0.1:8000/reports/incident?execution_id=<execution_id>&limit=50"
curl "http://127.0.0.1:8000/reports/incident?execution_id=<execution_id>&include_fix_executions=false&limit=50"
curl "http://127.0.0.1:8000/reports/incident?execution_id=<execution_id>&fix_event_type=rollback&limit=50"
curl "http://127.0.0.1:8000/reports/incident?agent_id=<agent_id>&after=2026-04-10T00:00:00%2B00:00&before=2026-04-10T23:59:59%2B00:00&limit=50"
curl -X POST http://127.0.0.1:8000/reports/incident/export -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-single.json\",\"agent_id\":\"<agent_id>\",\"include_fix_executions\":true,\"fix_event_type\":\"all\",\"limit\":50}"
curl -X POST http://127.0.0.1:8000/reports/incident/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-single.json\"}"
```

Incident reports bundle task context, agent context, execution logs, fix execution logs, module errors, emergency diagnoses, and related events for a single agent or task.
When execution_id is not supplied, fix execution logs are still correlated into incident reports through shared failure_id values present in related diagnoses/events.
`include_fix_executions=false` omits fix execution records and sets fix correlation counts to zero.
`fix_event_type` supports `all` (default), `apply`, and `rollback` for focused fix-event views.
Incident report payloads now include a `correlation` block with `failure_ids`, `fix_execution_count`, `correlation_sources`, and `resolved_execution_ids` to make linkage provenance explicit.
`correlation.warnings` flags ambiguous or filtered linkage states (for example `multiple_failure_ids_detected`, `fix_executions_excluded_by_filter`, and `fix_event_type_filtered:*`).
They are signed with `signing_version` and `report_hash`, and exported incident documents can be verified independently.

Emergency diagnosis snapshot export API:

```bash
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/export -H "Content-Type: application/json" -d "{\"path\":\".harness/diagnosis-snapshot.json\",\"source\":\"orchestrator.skill_execution\",\"agent_id\":\"<agent_id>\",\"limit\":50}"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/diagnosis-snapshot.json\"}"
```

Diagnosis snapshots are signed artifacts containing the paged `items` set and filter context used to produce it.

Run history export report:

```bash
curl "http://127.0.0.1:8000/reports/run-history?task_limit=10&log_limit=50"
curl "http://127.0.0.1:8000/reports/run-history?task_limit=10&log_limit=50&redact=false"
curl -X POST http://127.0.0.1:8000/reports/run-history/export -H "Content-Type: application/json" -d "{\"path\":\".harness/run-history-report.json\",\"task_limit\":10,\"log_limit\":50}"
curl -X POST http://127.0.0.1:8000/reports/run-history/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/run-history-report.json\"}"
curl -X POST http://127.0.0.1:8000/artifacts/cleanup -H "Content-Type: application/json" -d "{\"max_age_days\":7,\"include_logs\":false,\"dry_run\":true}"
curl "http://127.0.0.1:8000/reports/policy"
```

Export writes are restricted to configured execution allowed roots.
Export size is capped by `reports.max_export_bytes` and oversized exports are rejected.
Artifact cleanup is restricted to the storage directory and supports dry-run previews.

`/reports/run-history` includes signing metadata:

- signing_version
- report_hash (sha256 of deterministic report payload)
- redaction_applied
- config_snapshot (safe runtime config subset)
- recent_diagnoses (recent emergency diagnosis entries included in the signed payload)

`/reports/incident` also returns signing metadata:

- generated_at
- signing_version
- report_hash

Status now includes runtime module health:

```bash
curl http://127.0.0.1:8000/status
```

On internal module errors, orchestrator isolates failure to the task, publishes a
`MODULE_ERROR` event, and triggers logging-only Emergency diagnostics.
Agent skill execution timeouts and execution failures also flow through this path.

7. Run LM Studio health check:

```bash
python -m harness --workspace . lmstudio-check
```

8. Run a policy-constrained tool command:

```bash
python -m harness --workspace . run-tool shell_command --args "{\"command\":\"git status --short\"}"
```

PowerShell-friendly shortcut:

```bash
python -m harness --workspace . run-tool shell_command --command "git status --short"
```

## Configuration

- Defaults: harness/config_defaults.json
- Project overrides: harness.config.json
- Environment overrides: HARNESS_<SECTION>_<KEY>

LM Studio config keys:

- model.lmstudio.base_url (default: http://127.0.0.1:1234/v1)
- model.lmstudio.model (default: local-model)
- model.lmstudio.timeout_s (default: 45.0)

Phase 1 budget and tool policy keys:

- state_machine.default_budget.max_steps
- state_machine.default_budget.max_tokens
- state_machine.default_budget.max_duration_ms
- orchestrator.enable_subagents
- orchestrator.skill_execution_timeout_s
- scheduler.heartbeat_timeout_s
- tools.allowed_tool_names
- tools.blocked_tool_names
- tools.allowed_command_prefixes

Execution sandbox keys:

- execution.allowed_cwd_roots
- execution.allowed_command_prefixes
- execution.max_runtime_s
- execution.max_output_bytes

Optional API auth keys:

- api.require_api_key
- api.api_key
- api.require_admin_api_key
- api.admin_api_key

When enabled, send `x-api-key` header on all API calls.
Read-only endpoints use `api.api_key`. Mutating endpoints such as config updates,
report export, artifact cleanup, and scheduler control can require `api.admin_api_key`.

Report export keys:

- reports.redact_by_default
- reports.redacted_keys
- reports.max_export_bytes
- reports.cleanup_max_age_days
- reports.cleanup_glob

Skills market keys:

- skills.market_registry_file
- skills.market_installed_file
- skills.market_remote_cache_file
- skills.market_remote_status_file
- skills.market_remote_timeout_s
- skills.market_remote_min_sync_seconds
- skills.market_trusted_public_keys
- skills.market_allow_v1_hash_fallback

Logging retention keys:

- logging.cleanup_max_age_days

## Ops runbook

Recommended startup order:

1. Activate the virtual environment.
2. Confirm local model readiness if using LM Studio:

```bash
python -m harness --workspace . lmstudio-check
```

3. Confirm base runtime wiring:

```bash
python -m harness --workspace . status
```

4. Start the API:

```bash
python -m harness --workspace . serve-api --host 127.0.0.1 --port 8000
```

5. Check health and policy surfaces:

```bash
curl http://127.0.0.1:8000/status
curl http://127.0.0.1:8000/reports/policy
curl http://127.0.0.1:8000/scheduler/jobs
curl http://127.0.0.1:8000/agents
curl "http://127.0.0.1:8000/skills?related_node_id=tool:shell_command"
curl "http://127.0.0.1:8000/diagnostics/emergency?source=orchestrator.skill_execution&limit=10"
curl "http://127.0.0.1:8000/reports/incident?execution_id=<execution_id>&limit=20"
```

Operational triage flow:

1. Check `/status` for degraded module health.
2. Locate the relevant execution using `/logs?event_type=AGENT_SKILL_EXECUTED`.
3. Pull the focused incident bundle via `/reports/incident?execution_id=<execution_id>`.
4. Export a signed diagnosis snapshot via `/diagnostics/emergency/export`.
5. Verify the diagnosis snapshot signature via `/diagnostics/emergency/verify`.
6. If broader context is needed, export and verify run history via `/reports/run-history/export` and `/reports/run-history/verify`.
7. If artifacts accumulate, preview cleanup with `/artifacts/cleanup` using `dry_run=true` before deleting.

Optional Python helper workflow:

```python
from harness.api import HarnessApiClient

with HarnessApiClient(base_url="http://127.0.0.1:8000", api_key="<read_key>", admin_api_key="<admin_key>") as api:
  incident = api.get_incident_by_execution_id(execution_id="<execution_id>")
  exported = api.export_diagnosis_snapshot(path=".harness/diagnosis-snapshot.json", source="orchestrator.skill_execution")
  verified = api.verify_diagnosis_snapshot(path=".harness/diagnosis-snapshot.json")
```

Suggested incident commands:

```bash
curl "http://127.0.0.1:8000/logs?event_type=MODULE_ERROR&limit=20"
curl "http://127.0.0.1:8000/logs?event_type=EMERGENCY_DIAGNOSIS&limit=20"
curl "http://127.0.0.1:8000/logs?event_type=AGENT_SKILL_EXECUTED&limit=20"
curl "http://127.0.0.1:8000/diagnostics/emergency?agent_id=<agent_id>&skill_id=<skill_id>&limit=20"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/export -H "Content-Type: application/json" -d "{\"path\":\".harness/diagnosis-snapshot.json\",\"agent_id\":\"<agent_id>\",\"skill_id\":\"<skill_id>\",\"limit\":50}"
curl -X POST http://127.0.0.1:8000/diagnostics/emergency/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/diagnosis-snapshot.json\"}"
curl "http://127.0.0.1:8000/reports/incident?task_id=<task_id>&limit=50"
curl -X POST http://127.0.0.1:8000/reports/incident/export -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-single.json\",\"task_id\":\"<task_id>\",\"limit\":50}"
curl -X POST http://127.0.0.1:8000/reports/incident/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-single.json\"}"
curl -X POST http://127.0.0.1:8000/reports/run-history/export -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-report.json\",\"task_limit\":20,\"log_limit\":200}"
curl -X POST http://127.0.0.1:8000/reports/run-history/verify -H "Content-Type: application/json" -d "{\"path\":\".harness/incident-report.json\"}"
curl -X POST http://127.0.0.1:8000/artifacts/cleanup -H "Content-Type: application/json" -d "{\"max_age_days\":7,\"include_logs\":false,\"dry_run\":true}"
```

## Phase 1 smoke workflow

Run this sequence against a fresh API process:

1. `GET /status`
2. `POST /chat` with `local_stub`
3. `GET /tasks`
4. `GET /logs?limit=10`
5. `GET /memory/summary`
6. `GET /reports/run-history`
7. `POST /reports/run-history/export`
8. `POST /reports/run-history/verify`
9. `GET /scheduler/jobs`
10. `POST /scheduler/tick`

Expected Phase 1 smoke outcomes:

- status returns `ok: true`
- chat returns `success` boolean and response payload
- tasks and logs return arrays
- report export returns `ok: true` and a `report_hash`
- report verify returns `valid: true`
- scheduler endpoints return job metadata including guardrail fields

## Phase 1 closeout checklist

- `pytest -q` passes cleanly
- local API smoke workflow completes without manual patching
- LM Studio-backed `/chat` smoke request succeeds when the local server is available
- report export and verify both succeed
- cleanup dry-run produces expected candidate list
- scheduler metadata exposes failure and timeout guardrails
- README reflects the current operational surface
- latest changes are committed and pushed

## Phase 1 milestone

Phase 1 is now functionally closed as a local-first operational scaffold.

Delivered in this milestone:

- CLI and FastAPI control surfaces
- local stub and LM Studio model backends
- semantic and graph memory inspection APIs
- signed report export and verification
- artifact cleanup and retention controls
- read/admin API auth scopes
- scheduler failure and timeout guardrails
- operational runbook and smoke workflow

Recommended stable checkpoint tag: `phase1-milestone`

## Release and packaging

Build release artifacts:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Automated GitHub release workflow:

- Push a version tag like `v0.2.1` to trigger `.github/workflows/release.yml`.
- The workflow runs tests, builds `dist/*`, verifies package metadata, and publishes a GitHub Release with wheel and sdist artifacts attached.

Tag and publish example:

```bash
git tag v0.2.1
git push origin v0.2.1
```

Install the built wheel locally for smoke validation:

```bash
python -m pip install --force-reinstall dist/*.whl
harness --workspace . status
python -m harness --workspace . lmstudio-check
```

Release notes for this baseline are in `RELEASE_NOTES_0.2.4.md`.

## Notes

- This is phase 1 plus forward-compatible stubs.
- FastAPI server and full UI are intentionally deferred to later phases.
- Structured runtime events are logged to .harness/events.log.
