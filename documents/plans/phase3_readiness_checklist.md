# Phase 3 Readiness Checklist

## Goal

Start Phase 3 implementation with minimal discovery and clear contracts for scaffold tools.

## Ready Now

- Requested-tool compliance fails loudly when requested tools are not attempted.
- Run output includes browser proof artifacts:
  - `browser_proof`
  - `browser_proofs`
- Run output includes parsed test diagnostics:
  - `test_failure_summary`
  - `test_failed_count`
- Built-in editing and validation tools available for scaffolding workflows:
  - `write_file`, `append_file`, `replace_in_file`, `insert_at_line`, `delete_range`, `json_edit`, `yaml_edit`
  - `run_tests`, `lint_and_fix`, `run_project_check`
- Initial scaffold tool implemented:
  - `init_project` for `fastapi`, `vite-react`, and `static-site`
- Additional generators implemented:
  - `generate_component`
  - `generate_route`
- `init_project` may optionally install dependencies during scaffolding.
- Run-panel lifecycle controls implemented for generated app services:
  - `register`
  - `start`
  - `stop`
  - `restart`
- Auto-wire policy locked for this release:
  - generation remains isolated by default
  - `auto_wire=true` is accepted but deferred
- Release helper tools implemented:
  - `version_bump`
  - `generate_release_notes`
  - `tag_and_publish_release`
- Run output includes scaffold artifact visibility:
  - `created_paths`
  - `updated_paths`
  - `generated_app_service`

## Phase 3 API Contracts (Proposed)

- `init_project`
  - Inputs: `project_type`, `name`, `target_path`, `options`
  - Outputs: `created_paths`, `commands_to_run`, `notes`
- `generate_component`
  - Inputs: `framework`, `name`, `target_path`, `props_schema`
  - Outputs: `created_paths`, `updated_paths`
- `generate_route`
  - Inputs: `framework`, `route_path`, `target_path`, `with_loader`, `with_tests`
  - Outputs: `created_paths`, `updated_paths`

## Remaining Phase 3 Pre-Work

- Expand scenario tests for FastAPI and static-site component/route generation (not just React-focused paths).
- Add optional dry-run mode for release helpers before mutating git state.
- Improve release notes generation with category grouping (features/fixes/chore) from commit prefixes.

## Verification Gate for Phase 3 Completion

- Scaffold tools create expected files in a temp workspace and pass lint/test checks.
- Generated artifacts are visible in run panel as created/updated path sets.
- A full scaffold flow can run without manual file editing for baseline templates.
