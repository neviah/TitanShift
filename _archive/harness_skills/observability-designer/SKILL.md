---
name: observability-designer
description: "Design production-ready observability strategies including SLI/SLO frameworks, Prometheus metrics, structured logging, distributed tracing, alert optimization, and Grafana dashboard generation. Use when designing a /metrics endpoint, setting SLO targets, reducing alert noise, adding trace IDs to requests, or building a monitoring stack."
version: "1.0.0"
domain: engineering
mode: prompt
tags: [observability, metrics, slo, prometheus, grafana, tracing, alerting, monitoring]
source: "https://github.com/alirezarezvani/claude-skills/tree/main/engineering/observability-designer"
license: MIT
---

# Observability Designer

Design comprehensive observability strategies: SLI/SLO frameworks, metrics
endpoints, structured logging, distributed tracing, alert rules, and dashboards.

## When to Use

- Adding a `/metrics` Prometheus endpoint to a service
- Defining SLOs and error budgets for a new feature
- Designing structured log events with trace IDs
- Reducing alert fatigue (too many noisy alerts)
- Building a Grafana dashboard from scratch
- Adding request tracing through a multi-step workflow

## The Three Pillars

### Metrics (Prometheus format)

**Golden Signals (instrument these first):**
| Signal | Metric Name Pattern | Notes |
|--------|-------------------|-------|
| Latency | `service_request_duration_seconds{route,status}` | P50, P95, P99 histogram |
| Traffic | `service_requests_total{method,route,status}` | Counter |
| Errors | `service_errors_total{type}` | Counter; also error rate = errors/requests |
| Saturation | `service_queue_depth`, `service_active_runs` | Gauge |

**TitanShift-specific metrics to add:**
```
titanshift_requests_total{status}
titanshift_tool_duration_seconds{tool_name}
titanshift_artifacts_written_total{kind}
titanshift_runs_active
titanshift_run_duration_seconds{status}
```

### Structured Logging

Every log event should include:
```json
{
  "timestamp": "2026-04-18T14:32:00Z",
  "level": "INFO",
  "event": "tool_invoked",
  "trace_id": "uuid-v4",
  "run_id": "run-abc123",
  "tenant_id": "tenant-xyz",
  "tool_name": "append_file",
  "duration_ms": 42,
  "success": true
}
```

Log levels:
- `DEBUG` — fine-grained diagnostics (disabled in prod by default)
- `INFO` — key lifecycle events (request received, tool invoked, artifact written)
- `WARN` — degraded state, exceeded threshold, deprecated usage
- `ERROR` — recoverable failure (caught exception, tool error)
- `CRITICAL` — unrecoverable failure requiring immediate attention

### Distributed Tracing

Attach a `trace_id` (UUID v4) to every inbound request. Propagate it through:
- Tool calls (include in tool invocation log)
- Subagent spawns (pass as context)
- Artifact writes (embed in artifact metadata)
- Memory reads/writes

## SLI/SLO Framework

**SLI** — the measurable indicator (e.g., fraction of requests with latency < 200ms)
**SLO** — the target (e.g., 99.5% of requests complete within 200ms over 30 days)
**Error budget** — (1 - SLO) × window = allowable failures

**Burn rate alerting (multi-window):**

| Alert | Window | Burn Rate | Severity |
|-------|--------|-----------|----------|
| Fast burn | 1h / 5m | > 14× | Page (P1) |
| Slow burn | 6h / 30m | > 3× | Ticket (P2) |

Typical SLO targets:
| Service tier | Availability SLO | Latency SLO (P95) |
|-------------|-----------------|-------------------|
| Core API | 99.9% | < 500ms |
| Background runs | 99.5% | < 30s |
| Artifact storage | 99.99% | < 200ms |

## Alert Design Principles

**Every alert must be:**
1. **Actionable** — a human can do something about it right now
2. **Symptom-based** — alert on user-visible impact, not on cause
3. **Threshold-calibrated** — use historical data; avoid arbitrary round numbers

**Reduce noise by:**
- Hysteresis: different thresholds for firing vs. resolving
- Suppression: silence dependent alerts during known maintenance
- Grouping: combine related alerts into one notification

Alert fatigue checklist:
- [ ] Does this alert fire during normal traffic patterns? (raise threshold)
- [ ] Is there a runbook linked in the alert body?
- [ ] Does the alert auto-resolve when the condition clears?
- [ ] Is the same signal covered by a more precise alert? (deduplicate)

## Health Endpoint Design

`/health` should distinguish between states:

```json
{
  "status": "degraded",
  "checks": {
    "memory_backend": "healthy",
    "scheduler": "healthy",
    "tool_registry": "degraded",
    "model_adapter": "healthy"
  },
  "reason": "tool_registry: 3 tools failed registration"
}
```

Status values: `healthy` | `degraded` | `down`

## Prometheus Text Format Example

```
# HELP titanshift_requests_total Total HTTP requests
# TYPE titanshift_requests_total counter
titanshift_requests_total{status="200"} 1024
titanshift_requests_total{status="500"} 3

# HELP titanshift_tool_duration_seconds Tool execution latency
# TYPE titanshift_tool_duration_seconds histogram
titanshift_tool_duration_seconds_bucket{tool="append_file",le="0.1"} 980
titanshift_tool_duration_seconds_bucket{tool="append_file",le="1.0"} 1020
titanshift_tool_duration_seconds_sum{tool="append_file"} 45.2
titanshift_tool_duration_seconds_count{tool="append_file"} 1024
```
