# OfficeCLI Integration Spec

Defines TitanShift's OfficeCLI tool integration, including current behavior, required runtime constraints, and next-step hardening work.

---

## Purpose

Provide deterministic Office document operations for `.docx`, `.xlsx`, and `.pptx` using the `officecli` binary, with machine-readable tool outputs and artifact metadata suitable for UI rendering and run audit trails.

---

## Current Status

Implementation is present in `harness/tools/officecli.py` and registered from `harness/runtime/bootstrap.py`.

Registered tools:
- `officecli_create_document`
- `officecli_add_element`
- `officecli_view_document`
- `officecli_set_properties`
- `officecli_merge_template`
- `officecli_batch`

Runtime command dependency:
- `officecli` must be on PATH

Policy defaults:
- Allowed tool names include all OfficeCLI tools in `harness/config_defaults.json`
- Allowed command prefixes include `officecli`

---

## Tool Contracts

### officecli_create_document

Input:
- `path` (required): output file path with `.docx`, `.xlsx`, or `.pptx`

Output:
- `ok`, `path`, `document_type`
- `created_paths` or `updated_paths`
- `artifacts` with one Office artifact

Artifact shape:
- `kind`: `document.docx` | `document.xlsx` | `document.pptx`
- `mime_type`: corresponding Office OpenXML mime
- `generator`: `officecli_create_document`
- `backend`: `officecli_backend`
- `verified`: `true`

### officecli_add_element

Input:
- `path` (required)
- `type` (required)
- `parent` (optional, default `/`)
- `props` (optional object)
- `after` / `before` (optional anchors)

Output:
- `ok`, `path`, `parent`, `type`, `props`, `response`

### officecli_view_document

Input:
- `path` (required)
- `mode` (optional): `outline|stats|text|issues|annotated`
- `max_lines` (optional)

Output:
- `ok`, `path`, `mode`, `result`

### officecli_set_properties

Input:
- `path` (required)
- `props` (required object)
- `element_path` (optional, default `/`)

Output:
- `ok`, `path`, `element_path`, `props`, `response`

### officecli_merge_template

Input:
- `path` (required)
- `data` (required object mapping placeholders to values)

Output:
- `ok`, `path`, `placeholder_count`, `response`
- `artifacts` with modified Office document metadata

### officecli_batch

Input:
- `path` (required)
- `operations` (required non-empty array)
- `force` (optional)

Output:
- `ok`, `path`, `operation_count`, `force`, `response`

---

## Error Model

Tool wrappers fail with typed `RuntimeError` or `ValueError` when:
- `officecli` binary is missing
- required inputs are absent or invalid
- subprocess returns non-zero exit code
- output cannot be interpreted as expected

All errors must include actionable text (for example: install hint for missing binary).

---

## Security and Policy Constraints

1. Enforce path policy through TitanShift tool registry allowed paths.
2. Keep OfficeCLI calls deterministic (`--json` mode for parsing).
3. Disallow arbitrary shell composition around `officecli`; call binary directly.
4. Preserve structured return payloads; do not return unbounded raw process logs.

---

## Test Coverage Requirements

Minimum test coverage should include:
1. Binary missing path returns install guidance.
2. Create document returns artifact metadata and correct mime/kind.
3. Add/set/view/merge/batch handlers validate required arguments.
4. Non-zero subprocess code maps to deterministic error payload.
5. Merge template emits artifact with `placeholder_count` provenance.

Use subprocess mocking for unit tests to avoid external binary dependency in CI.

---

## Gaps and Next Extensions

1. Optional artifact previews for Office files (HTML/text extracts) in the UI.
2. Optional checksum/provenance hash in Office artifact payloads.
3. Add integration smoke test that runs only when `officecli` is available.
4. Add redaction-safe export path for document issue reports (`view issues`).

---

## Acceptance Criteria

- All six OfficeCLI tools remain registered and policy-allowed by default.
- Tool outputs stay machine-readable and stable for timeline rendering.
- Artifact records for create/merge are persisted and visible in run artifacts.
- Unit tests cover validation and subprocess failure cases.
- Docs and README installation guidance stay in sync with actual tool names.
