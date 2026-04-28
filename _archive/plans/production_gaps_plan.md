# TitanShift Production Gaps Plan

Addresses the five largest gaps standing between the current state and a hardened,
multi-user production deployment. Each gap maps to concrete tasks, acceptance
criteria, and a suggested build order.

---

## Gap 1 — Multi-Tenant Security & RBAC

**Current state:** API key lifecycle (rotation, expiry, scopes) is implemented.
No per-user isolation exists; every authenticated caller shares the same process
namespace, tool policy, and file system view.

**Why it blocks production:** A single bad actor or compromised key can read or
mutate another tenant's artifacts, runs, and memory. Required before any shared
or SaaS deployment.

### Tasks

1. **Tenant identity on every request** — attach a `tenant_id` to the request
   context in `harness/api/server.py`. Derive it from the resolved API key.
2. **Namespace artifact storage** — scope all artifact paths under
   `{storage_root}/{tenant_id}/...` so tenants cannot traverse each other's files.
3. **Namespace run and task store** — `harness/orchestrator/task_store.py` queries
   must filter by `tenant_id` so listing/reading runs is isolated.
4. **Scope tool policy per tenant** — `harness/execution/policy.py` should load
   the allowed-tool-names list from the tenant's key record rather than a single
   global config.
5. **Role-level key scopes** — define coarse roles (`read_only`, `operator`,
   `admin`) that gate which API routes and which tools a key may access.
6. **Regression tests** — add smoke tests that assert cross-tenant artifact and
   run reads return 403, not content from another tenant.

### Acceptance criteria

- A key scoped to tenant A cannot read artifacts, runs, or memory belonging to
  tenant B via any public API route.
- Tool policy overrides per tenant are enforced end-to-end (backend enforces; UI
  reflects the active scope).
- Existing single-user flows continue to pass unchanged.

---

## Gap 2 — Key Management UI

**Current state:** Backend fully implemented (create, rotate, revoke, expiry,
scope fields). Frontend has no key management surface; operators manage keys
only via direct API calls.

**Why it blocks production:** Operators cannot safely onboard users, rotate
compromised keys, or audit active credentials without a UI.

### Tasks

1. **`KeyManagementView` component** — new page at `/settings/keys` in the
   React frontend. Use the existing API client in `frontend/src/api/client.ts`.
2. **Key list table** — show key ID, description, scopes, expiry, last-used-at,
   and status (active / revoked / expired). Poll or use SSE for live status.
3. **Create key flow** — modal with description, scope checkboxes, optional
   expiry date picker. Display the raw key value once on creation (never again).
4. **Rotate action** — generate a new key and revoke the old one atomically.
   Confirm dialog with clear "copy new key before closing" warning.
5. **Revoke action** — with confirmation. Immediately reflects in the table.
6. **Audit log panel** — show last N events for a selected key (created, rotated,
   used, revoked) from the API's existing audit endpoint.
7. **Nav link** — add "API Keys" entry to the sidebar settings section.

### Acceptance criteria

- An operator can complete the full create → use → rotate → revoke lifecycle
  entirely from the UI.
- Raw key material is displayed exactly once at creation; subsequent views show
  only the masked prefix.
- Revoked/expired keys are visually distinct and cannot be used to authenticate.

---

## Gap 3 — Observability & Ops Readiness

**Current state:** Console logging via `harness/logging/logger.py`. No structured
traces, no metrics endpoint, no alerting hooks, no health dashboard.

**Why it blocks production:** Incidents are invisible until a user reports them.
No way to measure latency, error rates, or tool failure patterns. Release
readiness cannot be validated against objective metrics.

### Tasks

1. **Structured log events** — emit JSON log lines for key lifecycle events:
   request received, tool invoked (name, duration, success/error), artifact
   written, run completed, exception caught. Add `run_id`, `tenant_id`,
   `tool_name`, and `duration_ms` fields everywhere.
2. **`/metrics` endpoint** — expose Prometheus-format counters and histograms:
   `titanshift_requests_total{status}`, `titanshift_tool_duration_seconds{tool}`,
   `titanshift_artifacts_written_total{kind}`, `titanshift_runs_active`.
3. **`/health` endpoint hardening** — current health check is shallow. Extend to
   probe the memory backend, scheduler, and tool registry. Return `degraded` vs
   `healthy` with a reason map.
4. **Request tracing** — attach a `trace_id` (UUID) to every inbound request and
   propagate it through tool calls, subagent spawns, and artifact writes. Log it
   on every event for that request.
5. **Error budget alerts (config)** — add a `harness.config.json` block for alert
   thresholds (error rate, p95 latency). Log a WARN when exceeded so external
   alerting systems (PagerDuty, Slack webhook) can pick it up.
6. **Grafana/Prometheus quick-start** — add a `docker-compose.observability.yml`
   with Prometheus + Grafana pre-configured for the `/metrics` endpoint and a
   starter dashboard JSON.

### Acceptance criteria

- Every tool invocation and artifact write produces a structured log line with
  `trace_id`, `run_id`, `tenant_id`, duration, and outcome.
- `/metrics` returns valid Prometheus text format; Grafana dashboard shows
  request rate, error rate, and tool latency percentiles.
- `/health` distinguishes between healthy, degraded, and down states for each
  subsystem.

---

## Gap 4 — Migration Playbooks & Release Governance

**Current state:** Release notes exist. No schema migration tooling, no config
migration scripts, no documented upgrade path between versions, no changelog
automation.

**Why it blocks production:** Operators cannot safely upgrade a running
deployment. Breaking API or schema changes silently corrupt data or break
integrations.

### Tasks

1. **Schema versioning** — add a `schema_version` field to persisted state
   (task store SQLite schema, memory backends). Detect version mismatches at
   startup and refuse to start with a clear error and upgrade instruction.
2. **Migration scripts** — add a `scripts/migrate.py` (or CLI command
   `python -m harness migrate`) that applies incremental schema migrations. Use
   simple numbered SQL files under `harness/migrations/`.
3. **Config migration** — add a `harness config migrate` sub-command that reads
   an older `harness.config.json` format and outputs the current expected shape,
   with diff output for review.
4. **Deprecation policy** — define a one-version deprecation window in the
   README: fields removed in v`N` must be deprecated (logged as WARN) in v`N-1`.
5. **CHANGELOG automation** — add a `scripts/gen_changelog.py` that produces
   structured release notes from `git log --oneline` between two tags, grouped by
   `feat:`, `fix:`, `chore:`. Integrate into the release checklist.
6. **Release checklist** — add `documents/plans/release_checklist.md` covering:
   run smoke matrix, bump version in `pyproject.toml`, generate changelog,
   tag, push, and confirm CI green.

### Acceptance criteria

- Upgrading from any previous minor version to the latest runs `python -m harness
  migrate` and completes without manual SQL edits.
- Starting with a mismatched schema version prints a clear human-readable error
  and exits non-zero.
- A release takes one developer < 30 minutes end-to-end following the checklist.

---

## Gap 5 — Scale Posture (Queue & Worker Isolation)

**Current state:** Runs execute synchronously in the FastAPI request thread (or
a thin async wrapper). All runs share one process, one interpreter lock, and one
memory backend connection.

**Why it blocks production:** A long-running or expensive run starves all other
users. One runaway tool call crashes the entire service. No back-pressure or
concurrency limit exists.

### Tasks

1. **Run queue** — move run execution off the request thread. Add a simple
   in-process `asyncio.Queue`-based runner for local deployments and an
   interface that can be swapped for Redis/Celery for distributed deployments.
   The API returns a `run_id` immediately; the client polls or subscribes to SSE
   for status.
2. **Worker concurrency limit** — enforce a `max_concurrent_runs` config value
   (default: 4). Requests beyond the limit return `429 Too Many Requests` with a
   `Retry-After` header.
3. **Per-run timeout** — enforce `run_timeout_seconds` from config. A run that
   exceeds the wall-clock limit is cancelled with a `timeout` terminal state and
   its artifacts are preserved.
4. **Per-tool concurrency cap** — certain tools (e.g. `shell_exec`,
   `browser_action`) are expensive. Add a semaphore per tool-category in
   `harness/execution/runner.py` (max simultaneous shell evals, max browser
   sessions).
5. **Memory backend connection pooling** — `semantic_sqlite.py` uses a single
   connection. Switch to a connection pool (SQLite WAL mode + thread-local
   connections) so concurrent reads don't serialize.
6. **Load test** — add a `tests/test_load.py` that fires 10 concurrent run
   requests and asserts: all complete (no 500s), wall-clock < 2× serial time,
   no artifact ID collisions.

### Acceptance criteria

- 10 concurrent run requests complete without errors under the default worker
  limit.
- A run that exceeds `run_timeout_seconds` is cancelled cleanly and returns a
  `timeout` state rather than hanging indefinitely.
- `max_concurrent_runs` is respected: the (N+1)th request returns 429, not a
  queued delay.

---

## Suggested Build Order

| Order | Gap | Rationale |
|-------|-----|-----------|
| 1 | Gap 2 — Key Management UI | Unblocks operator self-service immediately; backend is done |
| 2 | Gap 3 — Observability | Enables informed decisions for all subsequent work |
| 3 | Gap 1 — Multi-Tenant RBAC | Requires observability instrumented first for audit trail |
| 4 | Gap 5 — Scale Posture | Queue/worker model builds on the run lifecycle already stabilized by RBAC |
| 5 | Gap 4 — Migration Playbooks | Last because schema stabilizes after RBAC + scale changes land |
