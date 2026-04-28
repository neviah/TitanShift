# TitanShift Artifact and Media Plan

This plan covers the next three product items after the current release stabilization work. It intentionally excludes local diffusion, LTX-style video generation, and other heavyweight generative media stacks. The focus is deterministic artifact creation that TitanShift can execute, verify, and ship quickly.

## 1. Conservative Roadmap

### Item 1: Deterministic Artifact Foundation

Goal: make artifact creation a first-class runtime capability instead of a loose collection of file writes.

- Add an artifact result contract shared by tools, runs, and the UI.
- Add an artifact backend registry so new artifact types plug in behind one runtime interface.
- Persist artifacts under a per-run directory with stable metadata and provenance.
- Surface artifact cards in run output with path, MIME type, generator, and proof metadata.

Initial artifact types:

- Markdown and HTML documents
- PDF reports rendered from HTML/Markdown templates
- Charts from structured JSON or CSV input
- SVG graphics and UI assets
- Hyperframes scene specs and deterministic video render jobs

Explicitly out of scope for this item:

- Diffusion image generation
- Text-to-video models
- Audio synthesis
- Asset training or fine-tuning workflows

Acceptance criteria:

- A tool can return one or more artifacts without inventing its own output schema.
- The run record captures created artifact paths and metadata.
- The UI can preview at least document, chart, and SVG outputs.

### Item 2: Artifact Authoring Tools

Goal: add a small set of opinionated tools that produce useful outputs immediately.

Planned tools:

- `generate_report`: produce Markdown, HTML, or PDF from structured inputs and templates.
- `generate_chart`: produce PNG or SVG charts from tabular data and chart configuration.
- `generate_svg_asset`: produce icons, diagrams, badges, simple illustrations, and UI graphics from structured instructions.
- `generate_hyperframes_scene`: produce a typed Hyperframes composition plus render config for short deterministic videos.

Rules for all tools:

- Inputs must be structured and reviewable.
- Outputs must be reproducible from the saved request payload.
- The tool must emit artifact metadata, not just file paths.
- Failures must explain whether the issue is template, data, renderer, or environment related.

Acceptance criteria:

- At least three artifact tools are production-ready.
- Each tool has smoke coverage and one realistic end-to-end example.
- Generated outputs are visible in the run panel and downloadable from the API.

### Item 3: Packaging, Review, and Delivery

Goal: make artifacts usable in real workflows without turning TitanShift into a design studio.

Deliverables:

- Artifact bundle export for a run, including metadata manifest and generated files.
- Basic preview endpoints for browser-safe formats.
- API responses that clearly separate final answer text from generated artifacts.
- Release-grade audit trail showing which tool, input, and backend produced each artifact.

Near-term UX expectations:

- A run can show multiple artifacts in one place.
- Users can inspect the source config behind an artifact.
- Users can distinguish draft artifacts from verified outputs.

Acceptance criteria:

- A single run can produce a report, a chart, and an SVG asset together.
- Exported bundles are self-describing and easy to archive.
- Artifact metadata is stable enough for downstream automation.

## 2. Architecture Proposal

### Runtime Model

Introduce a shared artifact contract:

```python
class ArtifactRecord(TypedDict):
    artifact_id: str
    kind: str
    path: str
    mime_type: str
    title: str
    summary: str
    generator: str
    backend: str
    provenance: dict[str, Any]
    preview: dict[str, Any] | None
```

Introduce a backend interface:

```python
class ArtifactBackend(Protocol):
    name: str

    async def render(self, request: ArtifactRequest) -> ArtifactResult:
        ...
```

Recommended first backends:

- `document_backend`: Markdown, HTML, PDF
- `chart_backend`: SVG and PNG charts from structured data
- `vector_backend`: SVG illustrations, badges, diagrams, UI assets
- `hyperframes_backend`: typed scene generation and optional render execution

### Storage Model

Recommended layout:

- `.titantshift/artifacts/<run_id>/<artifact_id>/artifact.json`
- `.titantshift/artifacts/<run_id>/<artifact_id>/output.*`
- `.titantshift/artifacts/<run_id>/<artifact_id>/inputs.json`

Why this shape:

- Keeps generated outputs grouped by run.
- Makes artifacts easy to bundle or delete.
- Preserves exact render inputs for reproducibility.

### Tool and API Integration

Required changes:

- Extend task output to include `artifacts` alongside `created_paths` and `updated_paths`.
- Add API serialization for artifact metadata and preview URLs.
- Keep existing file tools unchanged; artifact tools add structure on top rather than replacing them.

Recommended behavior:

- Artifact-capable tools should return both file paths and structured artifact entries.
- The API should expose artifact previews only for safe formats such as HTML, SVG, PNG, and PDF.
- Video generation should stay queue-based and optional, even when driven by Remotion.

### UI Integration

Minimum UI work for the first shipping pass:

- Artifact list in the Current Run panel
- Inline preview for SVG, image, HTML, and PDF outputs
- Download button and filesystem path display
- Provenance block showing tool, backend, and source inputs

## 3. Positioning Language

### Product Direction

TitanShift should be described as a deterministic artifact engine for agent workflows, not as a general-purpose AI media generator.

Core positioning:

- TitanShift can turn structured inputs into reports, charts, SVG graphics, and short code-driven videos.
- Every artifact is reproducible, inspectable, and attached to the run that created it.
- The system favors tool-backed generation over opaque one-shot media synthesis.

### What To Say Publicly

Recommended release language:

- "TitanShift now supports artifact-ready runs, so agents can generate concrete outputs like reports, charts, and graphics alongside their final answers."
- "Our media direction is deterministic and code-driven: documents, SVG assets, data visuals, and Hyperframes-based video compositions rather than heavyweight local generative models."
- "Artifacts in TitanShift are reviewable and reproducible, with provenance that shows exactly which tool and inputs produced each output."

### What Not To Promise Yet

- Full creative image generation
- General text-to-video generation
- Studio-grade design tooling
- Arbitrary multimedia pipelines without structured inputs

## Immediate Build Order

1. Add artifact contract, storage layout, and API serialization.
2. Ship `generate_report`, `generate_chart`, and `generate_svg_asset` as the first production tools.
3. Add UI artifact cards and preview support.
4. Add `generate_hyperframes_scene` after the first three artifact types are stable.