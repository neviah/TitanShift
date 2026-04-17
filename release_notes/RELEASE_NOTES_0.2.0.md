# TitantShift Harness 0.2.0

Release date: 2026-04-10

## Highlights

- Added signed emergency diagnosis snapshot export and verification APIs.
- Added incident report lookup and export support scoped by execution id.
- Added strict timestamp window validation for log, diagnosis, and incident query/export paths.
- Added reusable Python API helper client for execution incident lookup and diagnosis snapshot workflows.
- Added edge-case test coverage for empty pages, limit boundaries, invalid time windows, and unknown execution ids.
- Added performance guardrail tests for diagnosis pagination and execution-scoped incident report generation.

## API additions

- POST /diagnostics/emergency/export
- POST /diagnostics/emergency/verify
- GET /reports/incident supports execution_id
- POST /reports/incident/export supports execution_id

## Validation

- Test suite: 61 passed

## Upgrade notes

- Version updated from 0.1.0 to 0.2.0.
- Existing report signature verification remains backward-compatible for current v1 signed payloads.
