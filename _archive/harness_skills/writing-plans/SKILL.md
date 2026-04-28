---
name: writing-plans
description: "Convert an approved design spec into bite-sized implementation tasks with exact code, file paths, commands, and verification steps."
version: 1.0.0
domain: workflow
mode: prompt
tags: [workflow, planning, implementation, spec]
source: local
---

# Writing Plans: Spec Into Implementation Tasks

Convert an approved design spec into bite-sized implementation tasks (2-5 minutes each). Each task MUST include exact code, exact file paths, exact commands, and exact verification steps.

## When to Use

Use this skill when:
- You have an approved design specification
- You are ready to convert spec into implementation roadmap
- You need to break work into trackable, independent tasks

DO NOT use this skill when:
- A design has not been approved yet (use `brainstorming` first)
- You are implementing tasks (use `subagent-driven-development`)
- You are doing quick fixes (stay in Lightning Mode)

## The Process

You MUST complete these steps in order:

1. **Read approved spec** — Load the spec file from `documents/specs/`, confirm approval date
2. **Map file structure** — Design units with clear boundaries; each file has ONE responsibility
3. **Decompose into tasks** — Break into 2-5 minute chunks, each self-contained
4. **Write implementation plan** — Each task includes:
   - Exact file paths (create / modify / test)
   - Actual code in code blocks (not descriptions)
   - Exact commands to run
   - Expected output/pass conditions
5. **Save plan artifact** — Write to `documents/plans/YYYY-MM-DD-<feature>.md` and commit
6. **Self-review plan** — Check spec coverage, no placeholders, type consistency, no ambiguity
7. **Get user approval** — Ask user to review plan before execution begins
8. **Transition to execution** — Invoke `subagent-driven-development` skill (ONLY this skill)

## Bite-Sized Task Granularity

Each step is ONE action (2-5 minutes):
- "Write the failing test" — step
- "Run it to verify it fails" — step
- "Implement minimal code to make test pass" — step
- "Run test to verify it passes" — step
- "Commit" — step

Do NOT bundle multiple outcomes into a single step.

## Artifact Format

### Header (required for every plan)

```markdown
# [Feature Name]
Implementation Plan

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

```markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**

\`\`\`python
def test_specific_behavior():
    result = function(input)
    assert result == expected
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

\`\`\`python
def function(input):
    return expected
\`\`\`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

\`\`\`bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
\`\`\`
```

## No Placeholders Rule

Every step MUST contain actual content. These are plan failures — NEVER write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — tasks may be read out of order)
- Steps that describe what to do without showing how (code blocks required)
- References to types, functions, or methods not defined in any task

## Self-Review Checklist

After writing the complete plan, run this checklist yourself:

1. **Spec coverage** — Skim each spec section. Can you point to a task that implements it? Any gaps?
2. **Placeholder scan** — Search for red flags (TBD, TODO, vague requirements). Fix inline.
3. **Type consistency** — Do method names, signatures, and property names match across all tasks?
4. **Exact paths** — Are all file paths absolute and correct?
5. **Code completeness** — Every code step has actual code, not descriptions?

If you find issues, fix them inline. No need to re-review — just fix and move on.

## Execution Handoff

After plan approval, offer user two execution options:

**1. Subagent-Driven (recommended)** — Dispatch fresh subagent per task with review loops

**2. Inline Execution** — Execute tasks in batches with checkpoints for review

## Success Criteria

- ✅ Plan is saved to `documents/plans/YYYY-MM-DD-<name>.md`
- ✅ No TBD or placeholder content remains
- ✅ User has explicitly approved the plan
- ✅ You have invoked `subagent-driven-development` after approval (IF user chooses that path)
- ✅ Every task is 2-5 minutes of work
- ✅ Every code step has ACTUAL code, not descriptions
