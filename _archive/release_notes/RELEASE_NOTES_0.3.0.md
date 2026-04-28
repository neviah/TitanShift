# TitantShift Harness 0.3.0

Release date: 2026-04-10

## Highlights

- Completed major Phase 3 emergency and scheduler hardening slices.
- Added emergency fix lifecycle APIs with rollback-aware execution handling.
- Added signed reporting parity for emergency fix execution snapshots (query/export/verify).
- Expanded incident reports with fix execution correlation, provenance metadata, and filtering controls.
- Added scheduler maintenance registration endpoint and recurring maintenance telemetry jobs.
- Added emergency diagnosis consensus traceability with selected hypothesis and scored consensus entries.

## Validation

- Test suite: 80 passed locally.
- Signed report verification paths validated for run history, incident, diagnosis snapshot, and fix execution snapshot artifacts.

## Upgrade notes

- Version updated from 0.2.4 to 0.3.0.
- Incident report payload now includes a correlation metadata block:
  - failure_ids
  - fix_execution_count
  - correlation_sources
  - resolved_execution_ids
  - warnings
- Incident report query and export now support:
  - include_fix_executions
  - fix_event_type (all/apply/rollback)
