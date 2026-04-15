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

## Phase 2 (Next)

- Add `insert_at_line` and `delete_range` file-edit tools.
- Add `yaml_edit` structured editor with path updates.
- Add `run_tests` tool with test target selection and parsed failure summary.
- Add `lint_and_fix` wrapper for project-aware lint/fix.
- Add adapter-aware browser proof artifacts (final URL + evidence snippet + optional screenshot metadata).

## Phase 3 (Planned)

- Add project scaffold tools:
  - `init_project` (FastAPI/React/Vite/static)
  - `generate_component`
  - `generate_route`
- Add service lifecycle controls in run panel (start/stop/restart + health badge).
- Add release automation helpers:
  - `version_bump`
  - `generate_release_notes`
  - `tag_and_publish_release`

## Acceptance Criteria

- User can explicitly demand a repo tool and see whether it was attempted.
- File append requests no longer overwrite existing content.
- Run panel exposes enough telemetry to debug tool routing failures without opening raw logs.
