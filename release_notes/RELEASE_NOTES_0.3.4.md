# TitanShift Harness 0.3.4

Release date: 2026-04-17

## Highlights

- **Conversation history**: Multi-turn context is now passed from the frontend to the model on every chat turn, enabling coherent multi-step exchanges without losing prior context.
- **Geolocation tool**: New `get_location` builtin resolves the caller's city, region, country, timezone, and ISP from the server's outbound IP. No API key required.
- **Chat timestamps**: Each chat bubble now shows the time the message was sent, stamped in ISO format at append time and rendered inline.
- **CI stability**: All 137 smoke tests pass. Test assertions are now config-independent — superpowered mode tests explicitly set the flags they need rather than relying on local harness.config defaults.
- **Production + Artifact roadmap**: Added `documents/plans/production_roadmap.md` covering the six-phase build plan through artifact foundation, core coding loop, streaming UX, multi-file context, persistence, and execution safety.

## Bug Fixes

- **Conversation history timing bug (frontend)**: `priorMessages` was captured from `messages` state *after* `appendMessage` was called, so React's async state update meant the model received a malformed history that dropped the last assistant turn. Fixed by capturing the snapshot *before* the append.
- **CI: `test_defaults_load` assertion**: Test was asserting `deny_all_by_default is True` while the runtime default is `False`. Fixed to match actual config.
- **CI: `test_emergency_diagnosis_for_policy_blocked_skill_execution`**: Clearing `allowed_tool_names` had no effect when `deny_all_by_default` is `False`. Fixed by explicitly enabling deny-by-default before the block assertion and restoring it after.
- **CI: superpowered mode tests**: Three tests (`test_chat_superpowered_blocks_without_required_approvals`, `test_chat_superpowered_review_loop_attaches_review_result`, `test_workflow_metrics_endpoint_reports_lightning_and_superpowered`) failed when local config had approval/review flags disabled. Fixed by setting required flags in-test.

## New Tools

- `get_location` — resolves geolocation from outbound IP via ip-api.com. Returns `city`, `region`, `country`, `zip`, `latitude`, `longitude`, `timezone`, `isp`. Registered with `needs_network=True` and capabilities `["geo.ip", "location.city", "location.country"]`. Added to `allowed_tool_names` in default config.

## Validation

- Full smoke suite: **137 passed, 0 failed** ✅
- Geolocation live test: `"You are in Oviedo, Florida."` ✅
- Conversation history live test: two-turn recall of user-stated preference ✅

## Upgrade Notes

- Version bumped from 0.3.3 → 0.3.4
- No breaking API or config changes
- `get_location` and `web_browse` added to `allowed_tool_names` in `harness.config.json` — no action needed for fresh installs; existing installs should add them manually if `deny_all_by_default` may be toggled on

## What's Next (Phase 1 — Artifact Foundation)

See `documents/plans/production_roadmap.md` for the full plan. Immediate next items:

1. `ArtifactRecord` contract, storage layout, and API serialization
2. `generate_report`, `generate_chart`, `generate_svg_asset` tools
3. Artifact cards and inline preview in the run UI
