# last30days Integration Spec

Defines TitanShift's runtime integration for the `last30days` research skill as an executable tool surface with deterministic artifact output.

---

## Purpose

Enable live, multi-source social intelligence research (Reddit, X, YouTube, Hacker News, Polymarket, GitHub, web) via a controlled tool call that emits a reproducible Markdown brief artifact.

---

## Scope

In scope:
- Add one runtime tool wrapper for last30days execution
- Inject configured API keys from `harness.config.json` at runtime
- Emit `document.markdown` artifact with provenance
- Add test coverage with subprocess mocking

Out of scope:
- Re-implementing last30days internals
- Mandatory online integration tests in CI

---

## Current Baseline

Already present:
- Skill prompt file at `harness/skills/last30days/SKILL.md`
- Config namespace `skills.last30days` in `harness/config_defaults.json`

Missing:
- Executable tool wrapper in `harness/tools/`
- Runtime registration and tests for tool behavior

---

## Proposed Tool

Tool name:
- `last30days_research`

Implementation location:
- `harness/tools/last30days.py`

Registration:
- Called from runtime bootstrap alongside builtin and officecli tool registration

### Input Contract

Required:
- `topic` (string): research topic or question

Optional:
- `save_dir` (string): output directory override
- `emit` (string): `compact|full` (default from config)
- `max_sources` (integer): optional source cap
- `timeout_s` (integer): max runtime override (bounded)

### Output Contract

Success payload:
- `ok: true`
- `topic`
- `summary` (short text)
- `report_path` (normalized path)
- `created_paths` / `updated_paths`
- `artifacts` with one Markdown artifact

Artifact payload:
- `kind: document.markdown`
- `mime_type: text/markdown`
- `generator: last30days_research`
- `backend: last30days_backend`
- `verified: true`
- `provenance` includes:
  - `generated_at`
  - `topic`
  - `emit`
  - `source_count` (if available)

Failure payload:
- Deterministic error message from subprocess exit
- Includes stderr excerpt (bounded)

---

## Runtime and Environment Mapping

Read from config path:
- `skills.last30days.SCRAPECREATORS_API_KEY`
- `skills.last30days.XAI_API_KEY`
- `skills.last30days.OPENROUTER_API_KEY`
- `skills.last30days.BRAVE_API_KEY`
- `skills.last30days.emit`
- `skills.last30days.save_dir`

Environment injection strategy:
1. Start from a minimal inherited environment.
2. Add only explicit last30days keys when non-empty.
3. Pass through bounded runtime values (`emit`, save dir).

---

## Execution Strategy

Preferred command shape:
- `python -m last30days ...` when package entrypoint is available

Fallback:
- configurable script path if package module execution is unavailable

Hard constraints:
- explicit timeout
- bounded stdout/stderr capture
- no shell interpolation for user topic

---

## Security and Policy

1. Tool is network-capable by design; gate with existing tool allowlist and key-based access.
2. Do not log raw secret values in tool output or telemetry.
3. Keep saved outputs under allowed workspace paths.
4. Normalize and validate output path before artifact emission.

---

## Test Plan

Unit tests with mocking should cover:
1. Missing dependency/module produces actionable install error.
2. Successful subprocess result writes artifact and returns deterministic payload.
3. Timeout path produces bounded error message.
4. Config key injection passes only non-empty values.
5. Existing report path updates `updated_paths` (not `created_paths`).

Integration coverage:
- Optional smoke test guarded by dependency presence; skipped in default CI.

---

## Rollout Plan

Phase A:
1. Add tool module and registration.
2. Add unit tests with mocked subprocess.
3. Add README usage snippet.

Phase B:
4. Add optional smoke test for local environments.
5. Surface run-panel artifact card for produced research brief.

---

## Acceptance Criteria

- Tool is discoverable and callable in standard runs.
- Successful runs emit a Markdown artifact with provenance.
- Errors are deterministic and actionable.
- Unit tests pass without network requirements.
- Secrets are never echoed in logs or payloads.
