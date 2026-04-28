# Hook Events Spec

Defines TitanShift's hook event system. Derived from the
`PreToolUse / PostToolUse / Stop / SessionStart` hook model in
`affaan-m/everything-claude-code`, rewritten for TitanShift's Python
async architecture.

---

## Purpose

Hooks let skill authors and harness operators attach side-effects at well-defined
lifecycle points **without modifying core orchestrator or tool code**. Each hook
is a registered async callable that receives a typed payload and may return a
directive telling the harness what to do next.

Design constraints:
- Hooks are synchronous with respect to the lifecycle step they attach to
  (i.e. `PreToolUse` hooks complete before the tool runs).
- Hooks must not block indefinitely; a per-hook timeout is enforced.
- Hooks may not call other hooks recursively.
- Hook failures are logged as `HOOK_ERROR` events but do not crash the run
  unless the hook returns `action: "abort"`.

---

## Hook Points

| Hook Name | Fires When | Can Block | Can Abort |
|-----------|-----------|-----------|-----------|
| `SessionStart` | A new run begins (after task is created, before first LLM call) | No | No |
| `PreToolUse` | Before any registered tool is executed | Yes | Yes |
| `PostToolUse` | After a tool returns (success or error) | No | No |
| `PreLLMCall` | Before an LLM inference call is made | Yes | No |
| `PostLLMCall` | After an LLM inference response is received | No | No |
| `Stop` | Run completes (success, error, or cancellation) | No | No |
| `ArtifactEmit` | An artifact record is written to storage | No | No |
| `PlanReady` | Orchestrator produces a plan and waits for approval | Yes | Yes |

---

## Payload Types

### `SessionStart`
```python
@dataclass
class SessionStartPayload:
    task_id: str
    tenant_id: str
    description: str
    workflow_mode: str          # "lightning" | "deep" | "spec_first"
    model_backend: str
    started_at: str             # ISO 8601
    metadata: dict[str, Any]   # arbitrary task.input fields
```

### `PreToolUse`
```python
@dataclass
class PreToolUsePayload:
    task_id: str
    tenant_id: str
    tool_name: str
    tool_args: dict[str, Any]   # the arguments the LLM submitted
    call_index: int             # 0-based index within this run
```

**Return value:**
```python
@dataclass
class PreToolUseDirective:
    action: Literal["allow", "abort", "replace_args"]
    # "allow"        → proceed with the original tool_args
    # "abort"        → cancel this tool call; return error_message to LLM
    # "replace_args" → execute tool with modified_args instead
    modified_args: dict[str, Any] | None = None
    error_message: str | None = None
```

### `PostToolUse`
```python
@dataclass
class PostToolUsePayload:
    task_id: str
    tenant_id: str
    tool_name: str
    tool_args: dict[str, Any]
    result: dict[str, Any]      # tool output dict
    error: str | None           # None if tool succeeded
    duration_ms: float
    call_index: int
```

No return value — hooks here are observation-only.

### `PreLLMCall`
```python
@dataclass
class PreLLMCallPayload:
    task_id: str
    tenant_id: str
    model: str
    messages: list[dict]        # full message list about to be sent
    tools_schema: list[dict]    # tool schemas in this request
    call_index: int             # 0-based within this run
```

**Return value:**
```python
@dataclass
class PreLLMCallDirective:
    action: Literal["allow", "inject_message"]
    # "inject_message" → prepend injected_message to messages before sending
    injected_message: dict | None = None  # {"role": "system", "content": "..."}
```

### `PostLLMCall`
```python
@dataclass
class PostLLMCallPayload:
    task_id: str
    tenant_id: str
    model: str
    response_text: str
    tool_calls: list[dict]      # parsed tool calls in the response (may be empty)
    input_tokens: int
    output_tokens: int
    duration_ms: float
    call_index: int
```

No return value.

### `Stop`
```python
@dataclass
class StopPayload:
    task_id: str
    tenant_id: str
    success: bool
    error: str | None
    total_tool_calls: int
    total_llm_calls: int
    duration_ms: float
    artifacts: list[dict]       # ArtifactRecord dicts emitted during the run
    output: dict[str, Any]      # final task output dict
```

No return value.

### `ArtifactEmit`
```python
@dataclass
class ArtifactEmitPayload:
    task_id: str
    tenant_id: str
    artifact_id: str
    kind: str
    path: str
    mime_type: str
    title: str
    generator: str
```

No return value.

### `PlanReady`
```python
@dataclass
class PlanReadyPayload:
    task_id: str
    tenant_id: str
    plan_text: str              # the full plan markdown
    plan_tasks: list[str]       # parsed task list
    spec_text: str | None       # spec if generated
```

**Return value:**
```python
@dataclass
class PlanReadyDirective:
    action: Literal["approve", "reject", "modify"]
    # "approve" → continue with plan as-is
    # "reject"  → abort run with reason
    # "modify"  → replace plan_text with modified_plan_text before continuing
    modified_plan_text: str | None = None
    rejection_reason: str | None = None
```

---

## Registration API

```python
from harness.hooks import HookRegistry

# Obtain the registry from RuntimeContext
hooks = runtime.hooks  # HookRegistry

# Register a hook
hooks.register(
    event="PreToolUse",
    handler=my_pre_tool_hook,
    priority=50,          # lower number = runs first; default 50
    timeout_s=5.0,        # per-hook timeout; default 10s
    label="my_audit_hook",
)

# Unregister
hooks.unregister(label="my_audit_hook")
```

All handler functions must be `async def` and accept a single payload argument
of the matching type. `PreToolUse` and `PreLLMCall` handlers must return a
Directive; others return `None`.

---

## Execution Order

Multiple hooks for the same event run in priority order (lowest number first).
For `PreToolUse` and `PlanReady`, the directives are resolved in order:
- First `"abort"` or `"reject"` directive encountered wins; remaining hooks are skipped.
- If all return `"allow"` / `"approve"`, the last non-None `modified_args` /
  `modified_plan_text` is used.

---

## Built-in Hooks (shipped with harness)

| Label | Event | Purpose |
|-------|-------|---------|
| `tenant_tool_filter` | `PreToolUse` | Abort tool calls not in `key_record.allowed_tools` when non-empty |
| `audit_log` | `PostToolUse` | Emit `TOOL_AUDIT` event to the event bus for every tool call |
| `run_telemetry` | `Stop` | Write run telemetry summary to the log |

---

## Implementation Plan

### Phase A — Core infrastructure
1. Create `harness/hooks/` package with `registry.py`, `payloads.py`, `directives.py`.
2. Add `HookRegistry` to `RuntimeContext` in `bootstrap.py`.
3. Implement `execute_hooks(event, payload)` method — async, priority-ordered, timeout-guarded.
4. Register built-in hooks in `bootstrap.py`.

### Phase B — Orchestrator wiring
5. Fire `SessionStart` at the top of `run_reactive_task()`.
6. Fire `PreToolUse` / `PostToolUse` in `ToolRegistry.execute_tool()`.
7. Fire `PreLLMCall` / `PostLLMCall` around `ModelAdapter.complete()`.
8. Fire `Stop` in the `finally` block of `run_reactive_task()`.
9. Fire `ArtifactEmit` when artifact storage writes complete.
10. Fire `PlanReady` at the plan-approval gate in spec-first workflow.

### Phase C — Tests
11. Unit tests for `HookRegistry` — registration, priority, timeout, abort propagation.
12. Integration tests — `PreToolUse` abort returns error to LLM; `PostToolUse` audit log.

### Phase D — Skill hooks
13. Add hook registration support to `SKILL.md` frontmatter (`hooks:` key).
14. Auto-register skill-defined hooks when a skill is installed.

---

## SKILL.md Frontmatter Extension (Phase D)

```yaml
hooks:
  - event: PreToolUse
    handler: "harness.skills.my_skill.hooks:pre_tool_use"
    priority: 30
    timeout_s: 3.0
    label: "my_skill_tool_filter"
```

The handler value is a Python import path (`module:function`). The registry
resolves and imports the handler lazily at install time.

---

## Security Constraints

- Hooks run with the same process privileges as the harness. Skill-defined hooks
  from remote installs require `market_trusted_public_keys` verification.
- `PreToolUse` hooks that consistently abort (> 10 consecutive aborts) are
  auto-suspended and emit a `HOOK_SUSPENDED` event.
- Hook timeout defaults to 10 s. Hooks that time out emit `HOOK_TIMEOUT` and
  are treated as returning `action: "allow"` (fail-open) for `PreToolUse`,
  or `action: "approve"` for `PlanReady`.
