# TitanShift Repo Integration Plan

Covers each starred repo the user flagged. Each entry gets a verdict
(`ADOPT`, `ADAPT`, `CROSS-CHECK`, or `SKIP`) with specific integration tasks
or rationale for skipping.

---

## anthropic/skills — ADOPT (high priority)

**What it is:** The official Anthropic public skills repository (120K stars).
Contains the Agent Skills specification, reference implementations for
`docx`, `pdf`, `pptx`, `xlsx` skills, plus a full library of creative,
technical, and enterprise skills in `SKILL.md` format.

**Why adopt:** TitanShift already has a `harness/skills/` system and a
`schemas/skills_market_index.schema.json`. The official `SKILL.md` YAML
frontmatter format is the de-facto cross-harness standard. Aligning to it
makes TitanShift's skills portable to Claude Code, Codex, Cursor, and back.

**Integration tasks:**

1. Audit all existing skills in `harness/skills/` against the official
   `SKILL.md` schema (name, description, version fields). Update any that
   diverge.
2. Pull the `frontend-design` skill as a base for UI improvement guidance
   (this is also the foundation Impeccable builds on — see below).
3. Pull the `coding-standards` and `test-first-development` skills and
   register them in TitanShift's skill registry.
4. The `spec/` folder defines the Agent Skills spec — use it as a compliance
   reference when building TitanShift's own skill authoring tooling.
5. The `docx/pdf/pptx/xlsx` skills are source-available (not Apache). Study
   their structure to inform TitanShift's `generate_report` PDF skill.

**Effort:** Low — mostly reading and format-aligning existing files.

---

## iOfficeAI/OfficeCLI — ADAPT (medium priority)

**What it is:** AI-native CLI for Word, Excel, and PowerPoint (2K stars, very
active). Single binary with deterministic JSON output, path-based element
addressing, MCP server, and a `SKILL.md` for agent auto-discovery.

**Why adapt:** TitanShift's `generate_report` currently outputs PDF. OfficeCLI
adds docx/pptx/xlsx output with much richer formatting control. Agents can
compose multi-section Word reports or slide decks as artifacts. The MCP server
also makes it composable without bespoke wrappers.

**Integration tasks:**

1. Add `officecli` as an optional binary dependency in `requirements.txt`
   (or document it in README as a recommended runtime companion).
2. Create `harness/tools/officecli.py` with tool handlers:
   - `officecli_create_document` (type: docx/xlsx/pptx)
   - `officecli_add_element` (slide, paragraph, chart, table)
   - `officecli_view_document` (returns outline/text/JSON)
   - `officecli_merge_template` (merge JSON data into placeholders)
3. Each tool wraps `subprocess` calls to the binary with `--json` flag,
   parses the structured output, and emits an `ArtifactRecord` with the
   appropriate `mime_type` and `kind`.
4. Register in the tool registry alongside existing `generate_report`.
5. Incorporate OfficeCLI's `SKILL.md` into `harness/skills/` so the agent
   learns the CLI semantics automatically.
6. Add smoke tests for each wrapper (similar to existing `test_generate_report_*`).

**Effort:** Medium — ~1–2 days to build wrappers and tests.

---

## mvanhorn/last30days-skill — ADAPT (medium priority)

**What it is:** AI skill that searches Reddit, X, YouTube, HN, Polymarket, and
GitHub in parallel, scores results by engagement, and synthesizes a research
brief (22.6K stars, v3 with intelligent topic resolution).

**Why adapt:** TitanShift currently has no live-research capability. Adding
`/last30days` as a skill gives the agent real-time social intelligence before
coding decisions, competitive analysis, or context-gathering runs.

**Integration tasks:**

1. Clone `skills/last30days/SKILL.md` from the repo into
   `harness/skills/last30days/SKILL.md`.
2. The skill invokes Python scripts from the original repo. Either:
   - Add `last30days-skill` as a pip dependency (it ships a `pyproject.toml`), or
   - Copy the relevant Python entry points into `harness/skills/last30days/`
     as a bundled sub-package.
3. Wire environment variable pass-through so API keys (`X_BEARER_TOKEN`,
   `SCRAPE_CREATORS_API_KEY`, etc.) can be configured in `harness.config.json`
   and are injected at runtime.
4. The skill outputs research briefs as Markdown — emit as a
   `document.markdown` artifact with `verified: True` so it shows in the UI.
5. No smoke test needed for external network calls — add a unit test that mocks
   the subprocess and verifies artifact emission.

**Effort:** Low-medium — skill file copy + dependency wiring.

---

## nextlevelbuilder/ui-ux-pro-max-skill — ADOPT (medium priority)

**What it is:** Design intelligence skill (67K stars) that provides multi-platform
UI/UX guidance for AI agents.

**Why adopt:** TitanShift's frontend has no design quality enforcement layer.
This skill gives the agent design vocabulary, component-level guidance, and
platform-specific rules.

**Integration tasks:**

1. Fetch the `SKILL.md` from the repo and add to `harness/skills/ui-ux-pro/`.
2. Register in the skill market index (`schemas/skills_market_index.schema.json`)
   so it appears in the marketplace UI.
3. Review the skill for anything TitanShift-specific to strip (e.g. references
   to competing harnesses) and add TitanShift's component library context.

**Effort:** Very low — primarily file copy and index update.

---

## pbakaus/impeccable — ADOPT (medium priority)

**What it is:** Design language skill (20.5K stars) with 7 domain-reference files
(typography, color, spatial, motion, interaction, responsive, UX writing) and
18 commands (`/audit`, `/polish`, `/critique`, `/normalize`, etc.).

**Why adopt:** Directly improves TitanShift's frontend output quality. Builds on
`anthropic/skills/frontend-design` (which we're already importing). The 24-pattern
anti-pattern detector CLI (`npx impeccable detect`) can be added as a
pre-commit hook or CI step.

**Integration tasks:**

1. Copy `source/skills/impeccable/` into `harness/skills/impeccable/`.
2. Register in the skills market index.
3. Optionally add `npx impeccable detect frontend/src/` to the CI pipeline as
   a design-quality gate that reports (but doesn't block) on issues.
4. Incorporate the `/audit`, `/polish`, and `/critique` commands into TitanShift's
   skill commands registry so they're invocable from the chat UI.

**Effort:** Very low — file copy, index update, optional CI step.

---

## aaif-goose/goose — CROSS-CHECK ONLY

**What it is:** The AAIF/Linux Foundation open-source agent (42.6K stars, built
in Rust). Supports 15+ providers, 70+ MCP extensions, desktop + CLI + API.

**Why cross-check only:** Goose is a peer harness, not a component to adopt.
The value is architectural reference:

- **MCP ergonomics** — how goose registers, discovers, and namespaces MCP tools
  at runtime is a clean model for TitanShift's planned MCP extension layer.
- **Provider abstraction** — their `goose-llm` crate shows a clean pattern for
  swapping between Anthropic, OpenAI, Ollama, and Bedrock with a unified
  message schema.
- **Extension manifest format** — the extension TOML/JSON format is worth
  mirroring when TitanShift ships its own extension API.

**Action:** No code adoption. Read `crates/goose/src/providers/` and
`crates/goose-mcp/` when designing TitanShift's MCP extension layer (Phase 3).

---

## affaan-m/everything-claude-code — ADAPT SELECTIVELY (high value)

**What it is:** 160K-star harness performance system: 48 agents, 183 skills,
79 command shims, hooks, rules, MCP configs, AgentShield security scanner,
continuous-learning v2. The closest competitor reference in the ecosystem.

**Why adapt selectively:** This is a config/prompt system for Claude Code, not
a Python harness. Direct code adoption is mostly irrelevant. But the conceptual
model is the highest-signal reference we have for what a mature harness surface
looks like.

**Specific things to extract:**

1. **Hook architecture** — their `PreToolUse / PostToolUse / Stop / SessionStart`
   hook event model maps well to TitanShift's `state_machine/reactive.py`. Add
   the same named hook points so skill authors can attach side-effects without
   forking core code.
2. **AgentShield patterns** — the 102 static analysis rules for CLAUDE.md,
   settings.json, MCP configs, hooks, and agent definitions are a useful
   checklist for TitanShift's own harness security audit. Read
   `npx ecc-agentshield scan` output categories and ensure TitanShift's config
   defaults satisfy them.
3. **Continuous learning v2** — the instinct-based learning system (confidence
   scoring, import/export, evolve-to-skill pipeline) is the pattern TitanShift
   should implement for its memory module in Phase 5.
4. **Harness audit command** — the `/harness-audit` concept (reliability score,
   eval readiness, risk posture) is worth building into TitanShift's own
   diagnostics surface.
5. **Model routing** — the `/model-route` pattern (route tasks by complexity and
   budget) maps to TitanShift's `model/adapter.py`.

**Action:** Study as a reference; create `documents/specs/harness_audit_spec.md`
and `documents/specs/hook_events_spec.md` derived from the ECC model but
written for TitanShift's Python architecture.

---

## obra/superpowers — SKIP (already used)

**What it is:** 158K-star agentic skills framework and methodology.

**Why skip:** User already derived TitanShift's superpowers mode from this repo.
No new value to extract. Archive as a reference but take no further action.

---

## alirezarezvani/claude-skills — ADOPT SELECTIVELY (low effort, good value)

**What it is:** 232+ Claude Code skills covering engineering, marketing, product,
compliance, and C-level advisory (11.7K stars).

**Why adopt selectively:** This is a catalog — not a framework. Cherry-pick the
skills that TitanShift users are most likely to invoke:

**Priority picks:**

- `engineering/code-review` — complements TitanShift's existing code loop tools
- `engineering/security-review` — feeds into Gap 1 (RBAC/security audit work)
- `product/spec-writer` — useful for TitanShift's own planning workflow
- `compliance/*` — if TitanShift targets enterprise deployments

**Action:** Browse `https://github.com/alirezarezvani/claude-skills` once,
identify 5–10 skills to port, copy into `harness/skills/`, and register them.

---

## Summary Table

| Repo | Verdict | Priority | Effort |
|------|---------|----------|--------|
| anthropics/skills | ADOPT | High | Low |
| iOfficeAI/OfficeCLI | ADAPT | Medium | Medium |
| mvanhorn/last30days-skill | ADAPT | Medium | Low-Medium |
| nextlevelbuilder/ui-ux-pro-max-skill | ADOPT | Medium | Very Low |
| pbakaus/impeccable | ADOPT | Medium | Very Low |
| aaif-goose/goose | CROSS-CHECK | Low | None (reference only) |
| affaan-m/everything-claude-code | ADAPT selectively | High | Low (reading + spec writing) |
| obra/superpowers | SKIP | — | Already done |
| alirezarezvani/claude-skills | ADOPT selectively | Low | Low |

---

## Sequencing Recommendation

Batch 1 (this sprint — very low effort, high visibility):
- Adopt `anthropics/skills` format alignment
- Add `impeccable` and `ui-ux-pro` to `harness/skills/`
- Cherry-pick 5 skills from `claude-skills`

Batch 2 (next sprint):
- Build OfficeCLI tool wrappers (`officecli.py`)
- Port `last30days` skill + dependency wiring

Batch 3 (Phase 3/5 planning):
- Write `harness_audit_spec.md` and `hook_events_spec.md` derived from ECC
- Use goose's MCP/provider patterns as input to TitanShift's extension API design

Superpowers: no action.
