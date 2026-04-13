# Verification Before Completion: Evidence-Backed Done State

Before declaring a task complete, gather evidence that it actually works. Minimum: run the test, execute the script, check the output.

## When to Use

Use this skill when:
- Finishing any task in `subagent-driven-development`
- About to report "done" to the user
- Completing a feature branch that needs final verification

DO NOT use this skill for:
- Intermediate task reviews (those use code quality reviewer)
- Design or planning phases
- Questions or explanations

## The Process

1. **Identify what "works" means** — Read task spec, pass criteria, and verification steps
2. **Run all tests** — Full test suite, relevant tests, integration tests as specified
3. **Check output** — Does actual output match expected output?
4. **Manual verification** — If applicable, run the feature end-to-end
5. **Collect evidence** — Command output, pass/fail tallies, execution logs
6. **Report faithfully** — If tests fail, say so. If you didn't run a check, say so.
7. **If passing** — Mark task complete with evidence summary
8. **If failing** — Route back to implementer with specific failures

## Evidence Requirements

To declare something DONE, you MUST provide:

- **Command run** — The exact command you executed
- **Output snippet** — Relevant portion of output showing results
- **Pass/fail tally** — "5/5 tests passed" or "2 failures in auth module"
- **Timestamp** — When you verified it

Example:

```
✅ Verification Complete

**Command:** pytest tests/ -v
**Output:** 
  tests/auth/test_login.py::test_valid_user PASSED
  tests/auth/test_login.py::test_invalid_user PASSED
  tests/auth/test_password_reset.py PASSED
  5 passed in 0.24s

**Timestamp:** 2026-04-13 14:32 UTC
```

## What "Works" Means by Task Type

| Task Type | Verification |
|-----------|---|
| Feature | Feature test passes + manual E2E smoke test |
| Bug fix | Regression test passes + original bug no longer reproduces |
| Refactor | All existing tests pass (API unchanged) |
| Documentation | Links valid, examples run without error |
| Config/build | Build succeeds, artifact is usable |
| Utility function | Unit tests pass, no type errors |

## Failing Verification

If verification fails:

1. **Identify specific failures** — Which tests? Which output doesn't match?
2. **Route back to implementer** — Describe failures with exact output
3. **Implementer fixes** — Changes implementation, re-runs verification
4. **Iterate** — Keep verifying until it passes
5. **Never claim "mostly works"** — Either it passes or it doesn't

Example failure report:

```
❌ Verification Failed

**Command:** pytest tests/ -v
**Output:**
  tests/auth/test_login.py::test_valid_user FAILED
  AssertionError: Expected 200, got 401
  tests/auth/test_password_reset.py PASSED
  1 failed, 1 passed

**Issue:** Login test failing with 401. Check token generation in implementer fix.
```

## Common Pitfalls

❌ Claiming "all tests pass" when output shows failures
❌ Not running verification (just trusting the code looks right)
❌ Running only partial tests (run full suite relevant to task)
❌ Skipping manual verification for user-facing features
❌ Suppressing or simplifying failing checks to manufacture green result
❌ Saying "this should work" instead of actually running commands

✅ Always run the command, capture output
✅ Report outcomes faithfully (failures are OK, misreporting is not)
✅ Complete all relevant tests before marking done
✅ If you can't verify (no test exists, can't run),  say so explicitly

## Report Template

After verifying every completed task:

```
## Verification Summary

**Task:** [Task name]
**Branch:** [git branch if applicable]

### Tests Run
- Command: `[exact command]`
- Result: [X/Y passed, Z failed]
- Output: [relevant snippet]

### Manual Checks (if applicable)
- [Feature smoke test]: [result]
- [Integration point]: [result]

### Evidence Collected
- ✅ All specified tests pass
- ✅ Output matches expected
- ✅ No regressions detected

### Conclusion
**Status:** [DONE / NEEDS_FIX with specific issues]
```

## Integration

This skill is invoked after `subagent-driven-development` completes all tasks.

It gates the final "task complete" state: you cannot declare done without verification evidence.

If verification fails, it routes back to implementer subagent with specific failures for rework.

## Success Criteria

- ✅ Evidence provided for every passing task
- ✅ All relevant tests run and pass
- ✅ Manual verification completed for user-facing features
- ✅ Failures reported immediately (not hidden)
- ✅ No "probably works" claims — only "verified" or "not yet verified"

## Philosophy

Verification before completion is not about extra bureaucracy. It's about confidence.

The benefit of running `pytest -v` is not just that tests pass — it's that YOU KNOW they passed because you watched it happen. No assumptions, no guesses, just evidence.

That evidence is what lets you confidently report "done" to the user instead of "probably done, let's hope."
