# TitanShift Tool Reference

This document covers user-facing command surfaces: CLI commands, key API endpoints, and built-in tool families.

## CLI Commands

TitanShift currently exposes these subcommands:

- titanshift init
- titanshift serve-api
- titanshift run-task
- titanshift run-tool
- titanshift lmstudio-check
- titanshift status
- titanshift print-config
- titanshift migrate
- titanshift config migrate

### Example command snippets

Run a quick task:

```bash
titanshift run-task "Summarize current workspace status"
```

Run a tool manually:

```bash
titanshift run-tool read_file --args '{"path":"README.md"}'
```

## API Endpoints (Core)

### Health and status

- GET /health
- GET /status
- GET /metrics
- GET /metrics/workflow

### Chat and streaming

- POST /chat
- POST /chat/stream

### Tasks and approvals

- GET /tasks
- GET /tasks/{task_id}
- GET /tasks/{task_id}/timeline
- POST /tasks/{task_id}/resume
- POST /tasks/{task_id}/approve-plan

### Runs and telemetry

- POST /runs
- GET /runs
- GET /runs/{run_id}
- GET /runs/{run_id}/stream
- GET /telemetry/runs

### Configuration and operations

- GET /config
- POST /config
- GET /tools
- GET /skills
- GET /roles/templates

### Artifacts and reports

- GET /artifacts
- GET /artifacts/run/{task_id}/{artifact_id}/preview
- GET /artifacts/run/{task_id}/{artifact_id}/download
- GET /artifacts/run/{task_id}/bundle
- POST /artifacts/approve
- GET /reports/incident
- GET /reports/run-history

## Built-in Tool Families

The runtime includes built-in tools grouped into practical categories.

### File editing and workspace inspection

- read_file
- list_directory
- search_workspace
- write_file
- append_file
- replace_in_file
- edit_file
- patch_file
- insert_at_line
- delete_range
- rename_or_move
- delete_file
- json_edit
- yaml_edit

### Execution and quality checks

- shell_command
- run_project_check
- run_tests
- lint_and_fix
- install_dependencies

### Scaffolding

- create_directory
- init_project
- generate_component
- generate_route
- propose_wiring
- apply_wiring

### Release and artifact generation

- version_bump
- generate_release_notes
- tag_and_publish_release
- generate_report
- generate_chart
- generate_svg_asset
- generate_remotion_video
- generate_hyperframes_scene

### Optional integrations

- last30days_research

## Authentication behavior

When API key enforcement is enabled:

- Read operations require the read key
- Mutating/admin operations require the admin key

Configure these under api in harness.config.json or harness.config.local.json.
