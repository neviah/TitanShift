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
- Run output includes scaffold artifact visibility:
  - `created_paths`
  - `updated_paths`

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

- Add service lifecycle controls and health badges to the run panel so scaffolded apps can be started, stopped, and observed from the UI.
- Decide whether generators should auto-wire new components/routes into existing app entry points or keep generation isolated by default.
- Add release helpers after scaffold lifecycle support is in place.

## Verification Gate for Phase 3 Completion

- Scaffold tools create expected files in a temp workspace and pass lint/test checks.
- Generated artifacts are visible in run panel as created/updated path sets.
- A full scaffold flow can run without manual file editing for baseline templates.
