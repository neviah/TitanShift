# TitantShift Universal Harness (Phase 1 Scaffold)

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
- Orchestrator: reactive path + sub-agent toggle stub.
- Execution, emergency, scheduler, API hooks, graphify plugin stubs.
- CLI entrypoint runnable via python -m harness.

## Design decisions applied from your constraints

- Cloud model adapters exist but are optional.
- NetworkX-first graph backend behind adapter.
- SQLite semantic default; Chroma behind feature flag/stub.
- Graphify integrated as optional ingestion plugin.
- Custom memory engine inspired by MemPalace patterns.
- CLI-first MVP with API hook surface for future UI.
- Sub-agent spawning behind toggle only.
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
```

Runtime config API (in-memory override for current process):

```bash
curl http://127.0.0.1:8000/config
curl -X POST http://127.0.0.1:8000/config -H "Content-Type: application/json" -d "{\"key\":\"state_machine.default_budget.max_tokens\",\"value\":16000}"
```

Scheduler API (idle by default, explicit triggers only):

```bash
curl http://127.0.0.1:8000/scheduler/jobs
curl -X POST http://127.0.0.1:8000/scheduler/heartbeat
curl -X POST http://127.0.0.1:8000/scheduler/tick
curl -X POST http://127.0.0.1:8000/scheduler/jobs/scheduler_heartbeat/enabled -H "Content-Type: application/json" -d "{\"enabled\":false}"
```

Agents visibility API:

```bash
curl http://127.0.0.1:8000/agents
```

Skills and tools API:

```bash
curl http://127.0.0.1:8000/skills
curl "http://127.0.0.1:8000/skills?query=shell"
curl http://127.0.0.1:8000/tools
curl "http://127.0.0.1:8000/tools?query=shell"
```

Read-only memory inspect API:

```bash
curl http://127.0.0.1:8000/memory/summary
curl "http://127.0.0.1:8000/memory/semantic-search?query=alpha&limit=5"
curl "http://127.0.0.1:8000/memory/graph/neighbors?node_id=n1"
```

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

Status now includes runtime module health:

```bash
curl http://127.0.0.1:8000/status
```

On internal module errors, orchestrator isolates failure to the task, publishes a
`MODULE_ERROR` event, and triggers logging-only Emergency diagnostics.

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

When enabled, send `x-api-key` header on all API calls.

Report export keys:

- reports.redact_by_default
- reports.redacted_keys
- reports.max_export_bytes
- reports.cleanup_max_age_days
- reports.cleanup_glob

Logging retention keys:

- logging.cleanup_max_age_days

## Notes

- This is phase 1 plus forward-compatible stubs.
- FastAPI server and full UI are intentionally deferred to later phases.
- Structured runtime events are logged to .harness/events.log.
