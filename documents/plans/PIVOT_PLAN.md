# TitanShift Engine Pivot Plan

**Date:** April 28, 2026  
**Status:** IN PROGRESS  
**Decision:** Replace internal LLM orchestration engine with battle-tested open-source harnesses. Keep the TitanShift UI and shell (tasks, scheduler, workspaces, settings) entirely intact.

---

## Why We're Doing This

The internal Python orchestration engine (harness/state_machine, harness/orchestrator, harness/model) has a fundamental unfixable wiring bug: **`tools_schema_count: 0`** — tool definitions were never being passed to the model during task execution. This means the model runs completely blind with no native tool-calling capability. Despite extensive debugging and parser rewrites, the root cause was structural: the adapter layer between the LLM client and the tool registry was broken at its core.

Rather than continue fighting a broken foundation, we are plugging in two proven open-source harnesses that have already solved this problem at scale, used by hundreds of thousands of developers.

---

## What We're Keeping (Unchanged)

- `frontend/` — the entire React/Vite UI: chat, tasks, workspaces, scheduler, settings, model selector
- `harness/api/` — all FastAPI route definitions (the UI still calls these)
- `harness/scheduler/` — cron/job scheduling logic
- `harness/logging/` — logging infrastructure
- `harness/migrations/` — database migration files
- `harness/artifacts/` — artifact storage and serving
- `start.bat` — process launcher (updated to add sidecar process starts)
- `harness.config.json` — config file (add new harness-specific keys)

---

## What We're Replacing

| Component | Status | Replacement |
|---|---|---|
| `harness/state_machine/` | REPLACED | opencode (lightning) / openclaude (superpowered) |
| `harness/orchestrator/` | REPLACED | opencode / openclaude |
| `harness/model/adapter.py` | REPLACED | Each harness handles its own LLM communication |
| `harness/execution/` | REPLACED | Delegated to harness sidecars |
| `harness/model/` | REPLACED | Provider config passed to harness via env vars |
| `harness/memory/` | REVIEW | May keep lightweight context passing; heavy memory logic removed |
| `harness/skills/` | ARCHIVE | Not applicable in new architecture |
| `harness/emergency/` | ARCHIVE | Not applicable in new architecture |
| `harness/ingestion/` | ARCHIVE | Not applicable in new architecture |

---

## The Two Harnesses

### Lightning Mode → opencode

**Repo:** https://github.com/anomalyco/opencode  
**Stars:** 151k | **Contributors:** 874 | **Latest:** v1.14.28 (commits minutes ago)  
**Stack:** TypeScript + Bun  
**License:** MIT

**Why opencode for Lightning:**
- Built-in HTTP REST API (Hono server, `OPENCODE_EXPERIMENTAL_HTTPAPI=1` flag)
- Sessions map 1:1 to TitanShift Tasks
- Provider-agnostic: works with OpenRouter, Gemini, OpenAI, Ollama out of the box
- Two built-in agents: `build` (full file/bash access) and `plan` (read-only analysis)
- Desktop app available for Windows — clean install
- 779 releases; production-grade stability

**Integration endpoint:** `OPENCODE_EXPERIMENTAL_HTTPAPI=1 opencode serve` → HTTP on `localhost:3000`  
**Key API files:** `packages/opencode/src/server/routes/instance/httpapi/session.ts`, `event.ts`, `workspace.ts`

**How to install:**
```powershell
npm install -g opencode-ai@latest
# or
scoop install opencode
```

---

### Superpowered Mode → openclaude

**Repo:** https://github.com/Gitlawb/openclaude  
**Stars:** 24.8k | **Contributors:** 95 | **Latest:** v0.7.0 (commits 1 hour ago)  
**Stack:** TypeScript + Bun  
**License:** See LICENSE  
**Origin:** Fork of Claude Code, substantially modified for multi-provider support

**Why openclaude for Superpowered:**
- **Headless gRPC server** on `localhost:50051` — purpose-built for external integration
- Proto definition at `src/proto/openclaude.proto` — generate Python client in minutes
- Bidirectional streaming: tokens, tool states, and permission prompts all streamed
- `python/` directory already exists in repo — Python integration helpers present
- Agent routing config: different models for different task types (maps to "superpowered = strong model")
- Supports: OpenAI-compatible (OpenRouter ✅), Gemini, GitHub Models, Codex, Ollama
- VS Code extension included (bonus)

**Integration endpoint:** `npm run dev:grpc` → gRPC on `localhost:50051`  
**Proto file:** `src/proto/openclaude.proto` → `AgentService.Chat()` bidirectional stream

**How to install:**
```powershell
npm install -g @gitlawb/openclaude
```

---

## Target Architecture

```
TitanShift React UI  (port 5173)
         │
         │  REST / SSE / WebSocket  (unchanged)
         ▼
TitanShift FastAPI   (port 8000)
    ├── /tasks         ─────────────────────────────────── KEEP
    ├── /scheduler     ─────────────────────────────────── KEEP
    ├── /workspaces    ─────────────────────────────────── KEEP
    ├── /settings      ─────────────────────────────────── KEEP
    ├── /artifacts     ─────────────────────────────────── KEEP
    │
    ├── Lightning task execution
    │      └── OpenCodeAdapter (new, ~100 lines Python)
    │              └── HTTP proxy → opencode server  (port 3000)
    │
    └── Superpowered task execution
           └── OpenClaudeAdapter (new, ~80 lines Python)
                   └── gRPC client → openclaude server  (port 50051)

Sidecar Processes (managed by start.bat / process manager):
    opencode serve          (OPENCODE_EXPERIMENTAL_HTTPAPI=1)
    openclaude --grpc       (npm run dev:grpc)
```

---

## Implementation Steps

### Phase 1 — Install & Verify Harnesses (local)

1. Install opencode globally: `npm install -g opencode-ai@latest`
2. Verify opencode runs: `opencode --version`
3. Install openclaude globally: `npm install -g @gitlawb/openclaude`
4. Verify openclaude runs: `openclaude --version`
5. Start opencode HTTP server, confirm port 3000 responds
6. Start openclaude gRPC server, confirm port 50051 responds
7. Manually test a prompt via each harness CLI to confirm tool execution works

### Phase 2 — Build OpenCode Adapter (Lightning Mode)

1. Create `harness/adapters/opencode_adapter.py`
   - `start_server()` — spawn opencode as subprocess
   - `create_session(task_id, workspace_path)` → POST `/session`
   - `send_message(session_id, message)` → POST `/session/{id}/message`
   - `stream_events(session_id)` → GET `/session/{id}/events` (SSE)
   - `cancel_session(session_id)` → DELETE `/session/{id}`
   - `apply_model_config(provider, model, api_key, base_url)` → write env vars before spawn

2. Wire into `harness/api/` task execution routes (replace `state_machine` calls)
3. Test end-to-end: create task → opencode runs → files created → response streams to UI

### Phase 3 — Build OpenClaude Adapter (Superpowered Mode)

1. Install `grpcio` and `grpcio-tools`: `pip install grpcio grpcio-tools`
2. Download `src/proto/openclaude.proto` from openclaude repo
3. Generate Python stubs: `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. openclaude.proto`
4. Create `harness/adapters/openclaude_adapter.py`
   - `start_server()` — spawn openclaude gRPC server as subprocess
   - `run_task(message, working_directory)` → open `AgentService.Chat()` bidi stream
   - `stream_to_websocket(grpc_stream, ws)` — forward `TextChunk`, `ToolState`, `ActionRequired` events
   - `answer_permission(stream, approved)` — send `UserInput` back into the bidi stream
   - `cancel(stream)` — send `CancelSignal`
   - `apply_model_config(provider, model, api_key, base_url)` → write env vars before spawn

5. Wire into `harness/api/` task execution routes for superpowered mode
6. Test end-to-end: create superpowered task → openclaude runs → files created → streams to UI

### Phase 4 — Process Management

1. Update `start.bat` to launch opencode and openclaude sidecars on startup
2. Add health check endpoints for both sidecars in FastAPI
3. Add graceful shutdown: stop sidecars when FastAPI shuts down
4. Handle restart-on-crash for sidecar processes

### Phase 5 — Settings Integration

1. Confirm Settings page model/provider config flows through to adapter env vars
2. Add `lightning_model` and `superpowered_model` config keys to `harness.config.json`
3. Map OpenRouter base URL + API key from settings → opencode / openclaude env vars

### Phase 6 — Cleanup

1. Delete / archive: `harness/state_machine/`, `harness/orchestrator/`, `harness/model/`, `harness/execution/`
2. Delete / archive: `harness/skills/`, `harness/emergency/`, `harness/ingestion/`
3. Remove dead Python scripts from `scripts/`
4. Update README.md to reflect new architecture

---

## Model Config Mapping

| TitanShift Setting | opencode env var | openclaude env var |
|---|---|---|
| OpenAI-compatible base URL | `OPENAI_BASE_URL` | `OPENAI_BASE_URL` |
| API key | `OPENAI_API_KEY` | `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) |
| Model name | `OPENAI_MODEL` | `OPENAI_MODEL` |
| Use OpenAI compat mode | `CLAUDE_CODE_USE_OPENAI=1` | `CLAUDE_CODE_USE_OPENAI=1` |

Both harnesses treat OpenRouter as a standard OpenAI-compatible endpoint. Our current model (`google/gemini-2.5-pro` via `https://openrouter.ai/api/v1`) will work with both as-is.

---

## Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| opencode HTTP API changes (still experimental) | Medium | Pin to a specific version tag at install time |
| openclaude gRPC proto changes | Low | Copy proto into repo, pin openclaude version |
| Windows process spawn edge cases in start.bat | Medium | Test npx fallback; use absolute paths |
| Permission prompts from openclaude interrupt stream | Medium | Auto-approve non-destructive tools; surface destructive ones in UI |
| Node/Bun not installed on target machine | Low | Add Node.js check to start.bat preflight |

---

## Success Criteria

- [ ] Lightning mode: send a task prompt → opencode creates files in workspace → response streams to UI chat → task marked complete
- [ ] Superpowered mode: send a task prompt → openclaude executes multi-step tool loop → result streams to UI chat → task marked complete
- [ ] Settings model/provider selection flows through to both harnesses correctly
- [ ] Scheduler can kick off tasks in both modes
- [ ] Task cancel works (stops the sidecar session/stream)
- [ ] No regression in: task list, workspace switching, artifact viewing
