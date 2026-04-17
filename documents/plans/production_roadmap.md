# TitanShift Production Roadmap

This roadmap consolidates platform hardening with the deterministic artifact track from `documents/plans/artifact_media_plan.md`.

## Objectives

- Ship a production-ready coding workflow with safe edit/apply loops.
- Keep deterministic, inspectable artifact generation as a first-class capability.
- Add durable task memory and run outputs so sessions are resumable and auditable.
- Preserve fast local iteration while introducing policy and isolation guardrails.

## Guiding Principles

- Deterministic outputs over opaque one-shot generation.
- Structured tool I/O with explicit contracts and provenance.
- Tight human review points for risky operations.
- Build observability and testability into each phase.

## Phase 1: Artifact Foundation (from artifact_media_plan)

Scope:

- Introduce shared `ArtifactRecord` contract and API serialization.
- Add artifact storage layout by run/artifact ID with metadata + input payload capture.
- Add artifact cards and previews in the run UI.
- Ship deterministic artifact tools:
  - `generate_report`
  - `generate_chart`
  - `generate_svg_asset`
- Keep Remotion scene generation as next-in-line after first three tools stabilize.

Primary acceptance criteria:

- A run can return multiple artifacts in structured form.
- API separates final text answer from artifact metadata.
- UI previews document/chart/SVG artifacts inline.

## Phase 2: Core Coding Loop Tools

Scope:

- Harden and expose a production `read_file` tool contract (chunking, encoding, bounds checks).
- Add a `patch_file` tool with explicit unified-diff style apply flow and validation.
- Add dependency installation tooling with policy checks and audit events.
- Add safe file mutation ledger per run (`created_paths`, `updated_paths`, patch summaries).

Primary acceptance criteria:

- Agent can inspect and patch files in a reliable request/verify cycle.
- Package installs are policy-checked, logged, and reproducible.
- Tool outputs are machine-readable and UI-renderable.

## Phase 3: Multi-File Context + Auto-Wire

Scope:

- Add multi-file context ingestion for planner/reviewer roles with token budgeting.
- Add project graph indexing for routes, components, services, and dependencies.
- Add auto-wire helpers that propose or apply wiring changes for common framework patterns.
- Add context provenance so each generated change references source files used.

Primary acceptance criteria:

- Planner can reason across related files without brittle manual prompts.
- Auto-wire proposals are explainable and produce minimal, scoped edits.
- Review output includes why each changed file was selected.

## Phase 4: Streaming UX + Code Review Surfaces

Scope:

- Add streaming chat/task updates (SSE or websocket fallback) to remove long silent waits.
- Add side-by-side code editor and diff review surfaces in frontend.
- Add run timeline with tool calls, subagent steps, and artifact events.
- Add browser preview loop (render output + feedback channel into orchestrator).

Primary acceptance criteria:

- Users can follow progress live during long runs.
- Diff review and artifact preview are first-class in one run view.
- Browser-preview feedback can trigger targeted patch iterations.

## Phase 5: Persistence, Memory, and Metrics

Scope:

- Persist task outputs and key run events into the configured memory backend (`semantic_sqlite` now, optional chroma later).
- Store relationship edges in graph backend for cross-run retrieval (task -> files -> artifacts -> fixes).
- Add resumable runs and retrieval APIs for prior output blocks.
- Expand workflow metrics (lightning vs superpowered) with quality and latency slices.

Primary acceptance criteria:

- Task results survive process restarts and are queryable by API.
- Memory stores are used for operational persistence, not only semantic recall.
- Metrics endpoint supports release-readiness dashboards.

## Phase 6: Execution Safety and Production Readiness

Scope:

- Introduce non-container sandbox profile for command execution:
  - command allowlist and cwd/path constraints
  - restricted environment variables
  - per-command wall-clock + output limits
  - explicit network policy per tool
- Add stronger authn/authz model and API key lifecycle management.
- Add CI hardening: deterministic smoke matrix, policy tests, artifact integration tests.
- Add rollback and run-cancellation primitives.

Primary acceptance criteria:

- Risky execution paths are gated and observable.
- Auth and policy controls are enforceable in multi-user scenarios.
- CI catches policy regressions before release.

## Cross-Phase Deliverables

- Contract docs for all public tool payloads.
- Migration notes for config and API schema changes.
- Release notes template updates for workflow + artifact sections.

## Suggested Build Order

1. Phase 1 Artifact Foundation
2. Phase 2 Core Coding Loop Tools
3. Phase 4 Streaming UX + Diff Surfaces (parallel start with Phase 3 groundwork)
4. Phase 3 Multi-File Context + Auto-Wire
5. Phase 5 Persistence, Memory, and Metrics
6. Phase 6 Execution Safety and Production Readiness

Rationale:

- Artifacts and core file tools unlock immediate product value.
- Streaming + review UX improves trust while deeper intelligence matures.
- Persistence and safety hardening are essential before broad deployment.
