# Test-Driven Development: RED-GREEN-REFACTOR

Enforce TDD discipline in every task: write failing test, watch it fail, implement minimal code, watch it pass, commit.

## When to Use

Use this skill when:
- Implementing any feature or component during `subagent-driven-development`
- Writing bug fixes
- Adding new behavior to existing modules
- Code size > 5 lines

DO NOT use this skill for:
- Documentation-only changes
- Configuration changes that don't affect behavior
- Refactoring that doesn't change public API (use simpler patterns)

## The RED-GREEN-REFACTOR Cycle

Each cycle completes in order:

### RED Phase: Write Failing Test
- Write the test FIRST
- Test should describe intended behavior, not implementation
- Run test, confirm it FAILS with expected error
- Commit message: `test: add test for <behavior>`

### GREEN Phase: Minimal Implementation
- Write ONLY the code needed to make test pass
- No edge cases, no error handling (unless spec requires it)
- No refactoring, no "while I'm here" improvements
- Run test, confirm it PASSES
- Commit message: `feat: implement <behavior> to pass test`

### REFACTOR Phase: Improve Without Changing Behavior
- Rename variables, extract functions, remove duplication
- Public API unchanged; tests still pass
- Pick ONE refactoring per cycle (don't do many at once)
- Run tests after each refactoring
- Commit message: `refactor: <specific improvement>`

## Test Writing Anti-Patterns to Avoid

❌ "Write tests for the above" (without actual test code)
❌ Tests that check implementation details instead of behavior
❌ Tests with multiple unrelated assertions
❌ Tests that depend on execution order
❌ Tests that don't include an expected value/outcome
❌ I'll add error handling later (handle it now in RED phase)

## Implementation Anti-Patterns to Avoid

❌ Implementing code before writing test
❌ Writing "clever" code that passes test but has unclear intent
❌ Copy-pasting production code into test (test isolation matters)
❌ Adding features "while I'm here" that weren't in spec
❌ Skipping the refactor phase (code debt accumulates)

## Example: Adding a Validation Function

```markdown
### Task X: Add email validation

**RED: Write failing test**

\`\`\`python
def test_valid_email():
    assert is_valid_email("user@example.com") == True

def test_invalid_email_no_at():
    assert is_valid_email("user.example.com") == False
\`\`\`

Run: `pytest tests/utils/test_validation.py::test_valid_email -v`
Expected: FAIL — NameError: name 'is_valid_email' is not defined

**GREEN: Minimal implementation**

\`\`\`python
def is_valid_email(email):
    return "@" in email and "." in email
\`\`\`

Run: `pytest tests/utils/test_validation.py -v`
Expected: PASS — 2 passed

**REFACTOR: Improve code quality**

\`\`\`python
def is_valid_email(email):
    """Check if email has basic valid structure."""
    return "@" in email and "." in email and len(email) > 5
\`\`\`

Run: `pytest tests/utils/test_validation.py -v`
Expected: PASS — 2 passed (add edge case test if needed)
```

## Success Criteria for TDD

- ✅ Test fails before implementation
- ✅ Test passes after implementation
- ✅ No code written before test
- ✅ Each refactor verified with passing tests
- ✅ Implementation is minimal (not over-engineered)
- ✅ All commits are clean and single-purpose

## Commit Pattern

TDD creates natural commit breakpoints:

```bash
# RED
git add tests/path/test_file.py
git commit -m "test: add test for <specific behavior>"

# GREEN
git add src/path/file.py
git commit -m "feat: implement <behavior> to pass test"

# REFACTOR
git add src/path/file.py
git commit -m "refactor: <specific improvement>"
```

This creates a clear history where each commit is reviewable and reversible independently.

## Important Notes

- **Test isolation** — Each test MUST pass/fail independently
- **Test clarity** — Test name and assertions should document intended behavior
- **Minimal GREEN** — Resist the urge to gold-plate (edge cases belong in refactor if needed)
- **Refactor safety** — Run tests after EVERY refactor step, not just at the end
- **Don't skip RED** — Even if you "know" what to implement, write test first. You'll catch wrong assumptions.

## Integration

TDD is used within `subagent-driven-development` for every implementation task.

Implementer subagents are instructed to follow RED-GREEN-REFACTOR for every code step they take. Each cycle produces a git commit.

This keeps task history clean and lets reviewers understand exactly what changed and why.
