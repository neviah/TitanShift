# Harness Audit Spec

Defines TitanShift's `/harness-audit` diagnostic surface. Derived from the
`/harness-audit` concept in `affaan-m/everything-claude-code`, rewritten for
TitanShift's Python architecture.

---

## Purpose

`/harness-audit` produces a machine-readable and human-readable report that
captures the current reliability posture of a running TitanShift harness
instance. The report answers three questions:

1. **Reliability score** — how stable and predictable is this harness under load?
2. **Eval readiness** — is the harness configured to produce reproducible, verifiable outputs?
3. **Risk posture** — what configuration choices increase operational risk?

The audit is non-destructive and read-only. It never modifies state.

---

## Output Schema

```json
{
  "audit_version": "1.0",
  "generated_at": "<ISO 8601>",
  "harness_version": "<semver>",
  "reliability_score": 0..100,
  "eval_readiness": "ready" | "partial" | "not_ready",
  "risk_level": "low" | "medium" | "high" | "critical",
  "categories": {
    "<category_name>": {
      "score": 0..100,
      "findings": [
        {
          "id": "<AUDIT-XXX>",
          "severity": "info" | "warning" | "error" | "critical",
          "title": "<short title>",
          "detail": "<human-readable explanation>",
          "remediation": "<actionable fix>"
        }
      ]
    }
  },
  "summary": "<prose paragraph suitable for dashboard display>"
}
```

---

## Audit Categories

### 1. Configuration (`config`)

Check `harness.config.json` and `config_defaults.json` for unsafe or
incomplete settings.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-C001 | `api.require_api_key` is `false` and service is internet-exposed | warning |
| AUDIT-C002 | `api.api_key` is empty while `require_api_key` is `true` | error |
| AUDIT-C003 | `api.admin_api_key` is empty while `require_admin_api_key` is `true` | error |
| AUDIT-C004 | `model.default_backend` is `local_stub` in a production deployment | warning |
| AUDIT-C005 | `execution.run_timeout_seconds` is 0 (unbounded) | warning |
| AUDIT-C006 | `execution.max_concurrent_runs` > 20 | warning |
| AUDIT-C007 | `memory.storage_dir` is not writable | error |
| AUDIT-C008 | `reports.redact_by_default` is `false` | warning |

**Score formula:** start at 100; subtract per finding: `critical` −25, `error` −15, `warning` −5, `info` 0.

---

### 2. Authentication & Authorization (`auth`)

Inspect key-store records and tenant isolation configuration.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-A001 | No active API keys in key store AND `require_api_key` is `false` | info |
| AUDIT-A002 | Key store has admin-scoped keys with no `expires_at` set | warning |
| AUDIT-A003 | Any `tenant_id` is `_system_` on a key-store key (bypasses isolation) | info |
| AUDIT-A004 | `allowed_tools` is empty on all operator-scoped keys | info |
| AUDIT-A005 | More than 10 active admin-scoped keys | warning |

---

### 3. Tool Policy (`tools`)

Inspect ToolRegistry permission policy for unsafe defaults.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-T001 | `tools.deny_all_by_default` is `false` with no explicit allow list | warning |
| AUDIT-T002 | Shell-execution tools (`bash_eval`, `run_tests`) are allowed without `execution.policy` set | warning |
| AUDIT-T003 | `officecli` binary not on PATH but officecli tools are registered | info |
| AUDIT-T004 | More than 50 tools registered (schema size may degrade LLM routing) | warning |
| AUDIT-T005 | Tools with `required_commands` have their binary missing from PATH | warning |

---

### 4. Memory & Storage (`memory`)

Inspect memory backend health and storage quotas.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-M001 | Graph backend is `networkx` (in-memory only, not persistent) | info |
| AUDIT-M002 | Storage directory > 5 GB | warning |
| AUDIT-M003 | Semantic backend `chroma` or `sqlite` not initialized | warning |
| AUDIT-M004 | Memory write latency > 500 ms on last health check | warning |

---

### 5. Eval Readiness (`eval`)

Checks that the harness can produce stable, reproducible outputs for evaluation.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-E001 | `model.default_backend` is `local_stub` | critical (eval not possible) |
| AUDIT-E002 | No `test_smoke.py` test file found | warning |
| AUDIT-E003 | Last test run has failures | error |
| AUDIT-E004 | `orchestrator.skill_execution_timeout_s` is < 5 | warning |
| AUDIT-E005 | `reports.max_export_bytes` < 65536 | warning |

**Eval readiness verdict:**
- `ready` — zero errors/criticals in `eval` category
- `partial` — warnings only
- `not_ready` — one or more errors or criticals

---

### 6. Scale Posture (`scale`)

Inspect concurrency and rate-limiting settings.

| Check ID | Condition | Severity |
|----------|-----------|---------|
| AUDIT-S001 | `execution.max_concurrent_runs` is 1 (no parallelism) | info |
| AUDIT-S002 | WAL mode not enabled on task-store SQLite | warning |
| AUDIT-S003 | No `Retry-After` header configured for 429 responses | info |
| AUDIT-S004 | `execution.run_timeout_seconds` < 30 | warning |

---

## Scoring Algorithm

```
reliability_score = clamp(
    mean(category_scores) - critical_penalty,
    0, 100
)

critical_penalty = count(findings where severity == "critical") * 20

risk_level:
  score >= 80  → "low"
  score >= 60  → "medium"
  score >= 40  → "high"
  score < 40   → "critical"
```

---

## API Endpoint

```
GET /harness-audit
Response: AuditReport (schema above)
Authorization: require_admin_api_key
```

Optional query parameters:
- `?category=config,auth` — run only specified categories
- `?format=json|text` — machine JSON or human-readable text report

---

## Implementation Notes

- Run checks synchronously; total audit wall time target < 2 s.
- Do not write to disk during audit.
- All check results must be deterministic for the same config state.
- Implement in `harness/api/audit.py` with `run_audit(runtime) -> AuditReport`.
- Register endpoint in `server.py` alongside existing `/health` endpoint.
- Add a corresponding `GET /harness-audit` test in `tests/test_smoke.py`.

---

## Future Extensions

- **Continuous audit** — emit `AUDIT_FINDING` events to the event bus when a check degrades.
- **Audit history** — persist last 10 audit snapshots to the storage directory.
- **Trend scoring** — track reliability score over time; alert on > 10-point drops.
- **RBAC integration** — surface `allowed_tools` compliance per tenant as an audit category.
