# Testing Artifact Workspace

Purpose
- Keep all test-run outputs in one controlled location.
- Prevent root-directory clutter from smoke runs and matrix validation.

## Required Layout

Use this folder structure for all matrix runs:

- `Testing/P0_core_reliability/<run_id>/`
- `Testing/P1_frontend_quality/<run_id>/`
- `Testing/P2_web_file_integrity/<run_id>/`
- `Testing/P3_skill_activation/<run_id>/`
- `Testing/P4_creator_use_cases/<run_id>/`
- `Testing/P5_regression_gate/<run_id>/`

## Per-Run Contents

Each run folder must include:

- Generated artifacts (documents, media specs, html, svg, etc.)
- `report.json` with pass/fail summary
- `telemetry.json` with tools used, created paths, updated paths, and task ids
- Optional `notes.md` for manual observations

## Naming Convention

Use stable run IDs so evidence can be traced back to API tasks.

Recommended format:

- `<suite_short>-<yyyyMMdd-HHmmss>-<task_id_or_short_hash>`

Examples:

- `p1-20260419-231500-a1b2c3d4`
- `p4-20260419-231930-videohf`

## Video Generation Policy (HyperFrames)

For deterministic video workflow validation:

1. Use `generate_hyperframes_scene` to create:
- HyperFrames scene HTML
- HyperFrames render-job JSON

2. Store outputs under:
- `Testing/P4_creator_use_cases/<run_id>/video/`

3. Validate output metadata includes:
- `composition_id`
- `scene_path`
- `render_job_path`
- intended `output_mp4`

Note:
- Current harness integration generates scene and render-job artifacts.
- Actual MP4 rendering is executed by HyperFrames CLI/runtime from the generated render job.

## Office and PDF Policy

When validating business artifact workflows:

1. Use officecli tools for:
- `.docx`
- `.xlsx`
- `.pptx`

2. Use `generate_report` with `format=pdf` for deterministic PDF output.

3. Store outputs under:
- `Testing/P4_creator_use_cases/<run_id>/office_pdf/`

4. Verify generated files are non-empty and represented in telemetry/artifact metadata.

## Flood Guard

Fail any test run that writes generated artifacts outside `Testing/`.

Suggested check:
- Compare all `created_paths` and `updated_paths` against the `Testing/` prefix.
- Mark run failed on first violation.
