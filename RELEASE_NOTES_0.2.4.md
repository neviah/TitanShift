# TitantShift Harness 0.2.4

Release date: 2026-04-10

## Highlights

- Hardened CI and Release workflows to run on windows-latest, matching validated local environment.
- Switched workflow commands to python module invocation (python -m pip / python -m pytest) for command-path consistency.
- Retains prior test portability and Python 3.11 syntax compatibility fixes.

## Validation

- Test suite: 61 passed locally
- Local build: wheel and sdist generated

## Upgrade notes

- Version updated from 0.2.3 to 0.2.4.
- No API contract changes.
