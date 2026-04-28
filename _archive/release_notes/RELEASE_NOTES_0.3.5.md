# TitanShift Harness 0.3.5

Release date: 2026-04-17

## Highlights

- **Documentation reset**: Replaced the root README with a clear project narrative covering purpose, stable baseline, near-term roadmap, and practical setup steps.
- **Repository layout cleanup**: Moved versioned release note files out of the repo root into a dedicated `release_notes/` directory.
- **Release notes tooling update**: The builtin `generate_release_notes` tool now defaults to writing files under `release_notes/`.
- **CI stability follow-through**: Legacy root-level tests were updated to match current async and registry APIs, keeping CI aligned with current runtime interfaces.

## Changes

- Root README rewritten for clarity and onboarding value.
- `RELEASE_NOTES_*.md` files moved from root to `release_notes/`.
- `harness/tools/builtin.py` updated:
  - default output path changed from `RELEASE_NOTES_<version>.md`
  - to `release_notes/RELEASE_NOTES_<version>.md`
- Version bumped from `0.3.4` to `0.3.5`.

## Validation

- Full validated suite run:
  - `python -m pytest test_service_lifecycle.py test_tool_narrowing.py tests/test_smoke.py -q -p no:warnings`
  - **Result: 144 passed**

## Upgrade Notes

- Release notes are now stored in `release_notes/`.
- If you use custom tooling/scripts that read release notes from root, update paths accordingly.
