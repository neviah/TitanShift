---
name: subagent-driven-development
description: "Execute an approved implementation plan task-by-task using fresh subagents with spec compliance and code quality review gates after each task."
version: 1.0.0
domain: workflow
mode: prompt
tags: [workflow, subagent, orchestration, review]
source: local
---

# Subagent-Driven Development: Execute Plan With Reviews

Execute a plan task-by-task using fresh subagents, with two-stage review after each task: spec compliance first, then code quality.

## When to Use

Use this skill when:
- You have a complete, approved implementation plan
- Plan tasks are mostly independent
- You want quality gates and review loops before completion

DO NOT use this skill when:
- Plan has not been approved yet (use `writing-plans` first)
- You are in Lightning Mode (just execute inline)
- Tasks are tightly dependent (prefer sequential inline execution)

## The Process

**Per task:**

1. **Dispatch implementer subagent** — Provide full task text, context, file map
2. **Await implementer response** — Check for questions (NEEDS_CONTEXT), blockers (BLOCKED), or done (DONE/DONE_WITH_CONCERNS)
3. **If questions** — Answer them, provide context, re-dispatch implementer
4. **If blocked** — Assess blocker (context issue? task too large? plan wrong?), escalate or adjust
5. **If done** — Proceed to spec review

**Spec compliance review:**

1. **Dispatch spec reviewer subagent** — Provide implementer's work, plan spec, original requirements
2. **Await reviewer verdict** — Check: ✅ SPEC_COMPLIANT or ❌ ISSUES_FOUND
3. **If issues** — Implementer fixes, re-review
4. **If compliant** — Proceed to code quality review

**Code quality review:**

1. **Dispatch code quality reviewer subagent** — Provide implementer's work, spec, architecture
2. **Await reviewer verdict** — Check: ✅ APPROVED or ❌ ISSUES_FOUND
3. **If issues** — Implementer fixes, re-review
4. **If approved** — Mark task complete, move to next task

**After all tasks:**

1. **Dispatch final code reviewer** — Review entire branch implementation
2. **Await final verdict** — Check: ✅ READY_TO_MERGE or ❌ CONCERNS
3. **On ready** — Invoke `verification-before-completion` skill

## Implementer Status Handling

Implementer subagents report one of four statuses:

| Status | Action |
|--------|--------|
| **DONE** | Proceed to spec compliance review |
| **DONE_WITH_CONCERNS** | Read concerns; if about correctness, address before review; if observations, note and proceed to review |
| **NEEDS_CONTEXT** | Provide missing information and re-dispatch SAME subagent |
| **BLOCKED** | Assess blocker: context issue? task too large? plan wrong? Escalate or adjust, then re-dispatch |

**Never** ignore an escalation. If subagent says it's stuck, something needs to change.

## Review Loop Rules

- **Spec compliance** — Must pass BEFORE code quality review
- **Code quality** — Only after spec compliance ✅
- **Re-review** — If reviewer finds issues, implementer fixes and reviewer re-checks (same reviewer)
- **No skipping** — Both review stages required; self-review does not substitute

## Model Consideration (Single Model Constraint)

Since TitanShift uses one local model (Gemma 4 26B):
- Implementer subagent uses full model capacity
- Reviewer subagents use same model with focused prompts
- Spec reviewer gets strict compliance checklist to narrow focus
- Code reviewer gets architecture/quality checklist to narrow focus

## Task Context Format

Provide each subagent with:
- Full task text from plan (do NOT make subagent read files)
- File map (what gets created/modified)
- Related tasks (what came before, what comes after)
- Success criteria (run commands, expected output)

## Example Workflow

```
You: I'm using Subagent-Driven Development to execute this plan.

[Read plan file: documents/plans/feature-plan.md]
[Extract all 5 tasks with full text and context]

Task 1: Hook installation script

[Dispatch implementer with full task text]
Implementer: "Before I begin — should the hook be installed at user or system level?"
You: "User level (~/.config/superpowers/hooks/)"
Implementer: [implements, tests, commits]

[Dispatch spec reviewer]
Spec reviewer: ✅ Spec compliant — all requirements met, nothing extra

[Dispatch code quality reviewer]
Code reviewer: ✅ Strengths: Good test coverage. Issues: None. Approved.

[Mark Task 1 complete]

Task 2: Recovery modes

[Dispatch implementer with full task text]
Implementer: [no questions, proceeds]
Implementer: [implements, tests, commits]

[Dispatch spec reviewer]
Spec reviewer: ❌ Issues:
  - Missing: Progress reporting (spec says "report every 100 items")
  - Extra: Added --json flag (not requested)

[Dispatch implementer to fix]
Implementer: Removed --json, added progress reporting

[Dispatch spec reviewer again]
Spec reviewer: ✅ Spec compliant now

[Dispatch code quality reviewer]
Code reviewer: ✅ Approved

[Mark Task 2 complete]

[After all tasks...]
[Dispatch final code reviewer]
Final reviewer: ✅ All requirements met, ready to merge

Done!
```

## Success Criteria

- ✅ All tasks complete with spec compliance ✅
- ✅ All tasks complete with code quality ✅
- ✅ Final reviewer approves entire branch
- ✅ No open issues or concerns
- ✅ All commits are clean and traceable

## Common Pitfalls

❌ Start on main/master without explicit user consent
❌ Skip reviews (spec compliance OR code quality)
❌ Proceed with unfixed review issues
❌ Dispatch multiple implementers in parallel (conflicts)
❌ Make subagent read entire plan file (provide task text instead)
❌ Start code quality review before spec compliance ✅
❌ Let implementer self-review replace actual review (both needed)

✅ Give spec reviewer full text, not summary
✅ Give code reviewer architecture context
✅ Re-review after fixes (don't skip re-review loop)
✅ Track reviewer pass/fail reasons for metrics
✅ Mark tasks complete only after both reviews pass

## Integration

This skill expects:
- **Input:** Approved implementation plan from `writing-plans` skill
- **Output:** Completed implementation with reviewer approvals, ready for verification
- **Next:** Invoke `verification-before-completion` skill after all tasks pass

For truly independent parallel tasks, future version could dispatch multiple implementers with careful merge strategy, but v1 is sequential-per-task for safety.
