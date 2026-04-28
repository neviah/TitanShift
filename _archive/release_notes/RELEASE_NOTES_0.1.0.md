# TitantShift Harness 0.1.0

Initial Phase 1 milestone release.

## Highlights

- Local-first runtime with modular architecture and event-driven orchestration.
- FastAPI control plane covering status, chat, tasks, logs, scheduler, tools, skills, and memory inspection.
- LM Studio OpenAI-compatible backend support with local stub fallback.
- Signed run-history export and verification endpoints.
- Artifact cleanup with retention controls and dry-run mode.
- Scoped API authentication (read/admin).
- Scheduler safety guardrails: failure counters, timeout handling, auto-disable.

## Packaging

- Project packaged via PEP 621 in pyproject.toml.
- Wheel and source distribution artifacts are supported.
- Console entrypoint is available as: harness

## Known constraints

- Phase 1 focuses on local-first stability and observability.
- Advanced autonomous scheduler behavior and richer multi-agent flows are deferred to later phases.