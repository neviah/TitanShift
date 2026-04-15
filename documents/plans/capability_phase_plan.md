# TitanShift Capability Phase Plan

## Phase 1 (Implemented)

- Added `append_file` tool for true append semantics.
- Added `replace_in_file` tool for targeted text replacement edits.
- Added `json_edit` tool for structured JSON upserts via dot-path keys.
- Added run-panel visibility for:
  - `used_tools`
  - `requested_tools`
  - `fallback_used`
  - `primary_failure_reason`
- Added explicit tool-intent routing in reactive loop:
  - Detects requested tools from prompt text.
  - Narrows first-turn tool schema to requested tool(s) plus file support tools.
  - Removes hard bias that previously pushed all live lookups to `web_fetch`.

## Phase 2 (Implemented)

- Implemented `insert_at_line` and `delete_range` file-edit tools.
- Implemented `yaml_edit` structured editor with dot-path updates.
- Implemented `run_tests` tool with framework auto-detection, optional target, and parsed failure summary.
- Implemented `lint_and_fix` wrapper with framework auto-detection and optional fix mode.
- Implemented browser proof artifacts in task output (`final_url`, `evidence_snippet`, optional `screenshot_metadata`).
- Surfaced browser proof and parsed test-failure summary in Current Run panel.

## Phase 3 (Started)

- Implemented `init_project` scaffold tool for `fastapi`, `vite-react`, and `static-site`.
- Implemented `generate_component` for `vite-react`/`react` and `static-site`.
- Implemented `generate_route` for `vite-react`/`react`, `fastapi`, and `static-site`.
- Scaffold policy now supports optional dependency install execution for `init_project` via `npm install` or `python -m pip install -r requirements.txt`.
- Scaffold writes are now transactional with preflight conflict detection and rollback on downstream failure.
- Auto-wire behavior is now explicit: default isolated generation; `auto_wire` requests are accepted but intentionally deferred with explanatory notes.
- Implemented release automation helpers:
  - `version_bump`
  - `generate_release_notes`
  - `tag_and_publish_release`
- Release helpers now support `dry_run` mode to preview actions before file or git mutations.
- Release notes generation now groups commits into features, fixes, chore, and other sections using commit prefixes.
- Added FastAPI and static-site scenario coverage for `generate_route`, plus static-site scenario coverage for `generate_component`.

## Acceptance Criteria

- User can explicitly demand a repo tool and see whether it was attempted.
- File append requests no longer overwrite existing content.
- Run panel exposes enough telemetry to debug tool routing failures without opening raw logs.
- Run panel shows browser proof artifact fields for browser-capable tool runs.
- Test runs expose parsed failure summaries and failed-count signals.
- Scaffold runs expose `created_paths` and `updated_paths` in task output.
- Scaffold generators fail cleanly when targets already exist and `overwrite=false`, without partial writes.

## Next Planning Reference

- Artifact and media roadmap items 1 through 3 are documented in `documents/plans/artifact_media_plan.md`.
