---
name: brainstorming
description: "Structured ideation before any creative or implementation work. Produces an approved design spec before any code is written."
version: 1.0.0
domain: workflow
mode: prompt
tags: [workflow, planning, design, spec]
---

# Brainstorming: Ideas Into Designs

You MUST use this skill before any creative work — creating features, building components, adding functionality, or modifying behavior. Never skip this step, even for "simple" projects.

## When to Use

Use this skill when:
- Building something new from scratch
- Adding a significant feature or component
- Refactoring behavior rather than just code style
- User asks "build me X" or "create Y"

DO NOT use this skill for:
- Bug fixes (go straight to implementation)
- Documentation-only changes
- Single-line edits
- Explanations or technical questions

## The Process

You MUST complete these steps in order. Treat them as mandatory checks:

1. **Explore project context** — Read existing files, architecture, recent commits
2. **Ask clarifying questions** — One at a time, understand purpose/constraints/success criteria
3. **Propose 2-3 approaches** — With trade-offs and your recommendation
4. **Present design sections** — In bite-sized sections, get approval after each
5. **Write spec artifact** — Save to `documents/specs/YYYY-MM-DD-<topic>-design.md` and commit
6. **Self-review spec** — Check for placeholders, contradictions, ambiguity, scope issues
7. **Get user approval** — Ask user to review spec file before proceeding
8. **Transition to planning** — Invoke `writing-plans` skill (ONLY this skill, nothing else)

## Key Principles

- **One question at a time** — Don't overwhelm with multiple questions
- **Multiple choice preferred** — Easier to answer than open-ended when possible
- **YAGNI ruthlessly** — Remove unnecessary features from all designs
- **Explore alternatives** — Always propose 2-3 approaches before settling
- **Incremental validation** — Present design, get approval before moving on

## Artifact Output

- **Location:** `documents/specs/YYYY-MM-DD-<brief-topic>-design.md`
- **Format:** Markdown with sections for architecture, components, data flow, error handling, testing
- **Header:** Date created, status (draft/approved), approval date
- **Checklist:** Include placeholder scan, consistency, scope, ambiguity checks before user review

## Success Criteria

- ✅ User has explicitly approved the design
- ✅ Design document is committed to git
- ✅ No placeholders (TBD, TODO, etc.) remain
- ✅ You have invoked `writing-plans` skill ONLY after all approvals

## Anti-Pattern: Skipping Design

Every project goes through brainstorming, even:
- Todo lists
- Single-function utilities
- Config changes
- "Simple" projects

The design can be short (a few sentences), but you MUST present it and get approval.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it.
</HARD-GATE>
