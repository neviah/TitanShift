# TitanShift

TitanShift is a local-first AI engineering harness for building, testing, and operating agent workflows with strict runtime controls.

It combines:
- A Python orchestration runtime (tools, skills, memory, scheduler, diagnostics)
- A FastAPI control plane for chat, tasks, artifacts, and ops endpoints
- A React frontend for interactive workflow execution and review

## What This Project Is For

TitanShift is designed for teams that want agent-assisted development without giving up control.

Core goals:
- Deterministic, inspectable tool execution instead of opaque one-shot generation
- Strong policy controls for files, commands, and network access
- Incident visibility and rollback-friendly operations
- Progressive path from fast local iteration to production-grade execution

## Current Baseline (v0.3.x)

What is stable now:
- Reactive orchestration loop with tool calling
- Lightning and Superpowered workflow modes
- Agent skill assignment and scoped execution
- API task/log/history surfaces
- Artifact listing and report/export primitives
- Smoke + root test suites passing in CI

## What We Are Building Next

Near-term roadmap focus:
- Artifact Foundation: structured artifact contract, storage, metadata, preview
- Core Coding Loop: hardened read/patch/install tools and safer edit cycles
- Streaming + Diff UX: live run updates and better review surfaces
- Persistence + Memory: stronger cross-run recall and task output durability
- Execution Safety: tighter sandboxing and production auth/policy hardening

See:
- documents/plans/production_roadmap.md
- documents/plans/artifact_media_plan.md

## Project Layout

- harness/: runtime, orchestrator, tools, API, memory, scheduler
- frontend/: React UI
- tests/: smoke/integration tests
- documents/: design docs and plans
- release_notes/: versioned release notes

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

3. Run the API:

```bash
python -m harness --workspace . serve-api --host 127.0.0.1 --port 8000
```

4. (Optional) Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

5. (Optional) Install the `officecli` binary to enable Office document tools (`officecli_create_document`, `officecli_add_element`, `officecli_view_document`, `officecli_set_properties`, `officecli_merge_template`, `officecli_batch`):

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.ps1 | iex
```

Verify: `officecli --version`. If not found after install, open a new terminal and try again.

6. Run tests:

```bash
python -m pytest -q -p no:warnings
```

## Configuration

Primary config file:
- harness.config.json

Local override template:
- harness.config.local.example.json

## Release Notes

All release notes are stored under:
- release_notes/

## License

No explicit license file is currently included in this repository.
