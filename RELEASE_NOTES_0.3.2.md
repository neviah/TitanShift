# TitantShift Harness 0.3.2

Release date: 2026-04-16

## Highlights

- **Fixed web_browse tool execution ordering**: Model now correctly selects and executes browser tasks as requested, enforcing mandatory tool execution before support tools.
- **Enhanced scheduler task orchestration**: Implemented mandatory-tool detection for explicit "use <tool>" phrasing, with proper execution ordering (repo/browser tools before support tools like append_file/read_file).
- **Hardened web_browse implementation**: Added browser user-agent string and Reddit fallback host handling (old.reddit.com) to bypass anti-bot detection.
- **Fixed tool alias normalization**: Mapped `list_files` → `list_directory` and `web.browse` → `web_browse` for consistent tool invocation.

## Bug Fixes

- **Tool Selection Logic**: Fixed state machine tool detection to enforce requested/mandatory tools before support tools. Previously, model could optimize away explicit browser/file operations.
- **Premature Completion**: Prevented task finalization when mandatory tools remain unattempted, ensuring full execution chains (e.g., web_browse → append_file → read_file).
- **Anti-bot Handling**: web_browse now retries with `old.reddit.com` and relaxed wait conditions on standard Reddit domain failures.

## Validation

- Focused regression test: `test_camofox_same_prompt_enforces_requested_repo_tool_before_support_tools` ✅ passing
- End-to-end integration: web_browse + append_file + read_file chain execution ✅ verified
- Tool execution order enforced: browser tasks execute before file operations ✅ confirmed

## Upgrade Notes

- Version updated from 0.3.1 to 0.3.2
- No breaking changes to API or configuration
- Existing tasks benefit from improved tool execution reliability
- Scheduler now properly enforces tool ordering for complex workflows

## Commits Included

- fix: enforce requested/mandatory tool execution order for browser workflows
  - Add alias mapping list_files→list_directory and web.browse→web_browse
  - Detect explicit tool intents from natural phrasing (browser/browse/list files)
  - Restore repo+camofox intent mapping for repo intake tool selection
  - Add mandatory-tool detection for prompts that explicitly say 'use <tool>'
  - Enforce ordering: requested repo/browser tools must be attempted before support tools
  - Prevent premature finalization when mandatory tools remain unattempted
  - Harden web_browse with browser UA and reddit fallback host handling
