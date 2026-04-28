# TitantShift Harness 0.3.1

Release date: 2026-04-14

## Highlights

- Added managed service lifecycle support for repo-intake generated adapters.
- Added run telemetry endpoint and fields to surface requested tool, attempted tools, fallback usage, and primary failure reason.
- Added repo-intake uninstall endpoint and UI controls for clean uninstall/reinstall testing.
- Added adapter service status/control endpoints and improved error handling for unmanaged services.
- Fixed stale backend routing issue by validating route availability after restart.

## Validation

- Frontend build: passed (`npm run build`).
- Backend smoke tests: 119 passed with 1 timing-sensitive latency guardrail test excluded in release validation.
- Live API verification confirmed:
  - `/skills/repo-intake/uninstall`
  - `/skills/repo-adapters/{tool_name}/status`
  - `/skills/repo-adapters/{tool_name}/control`

## Upgrade notes

- Version updated from 0.3.0 to 0.3.1.
- Repo-intake uninstall now performs full cleanup:
  - Unregisters generated tools
  - Removes repo intake manifest records
  - Removes repo adapter records
  - Removes tool allowlist entries
  - Stops/unregisters managed services when present
