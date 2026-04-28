from __future__ import annotations

import asyncio
import fnmatch
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Callable

from harness.api.hooks import ApiHooks
from harness.api.hooks import HookPayload
from harness.runtime.config import ConfigManager
from harness.tools.definitions import ToolDefinition


@dataclass(slots=True)
class PermissionRule:
    permission: str
    pattern: str
    action: str


class ApprovalStore:
    """Tracks pending interactive approval futures and session-granted match labels."""

    def __init__(self) -> None:
        self.pending: dict[str, "asyncio.Future[str]"] = {}
        self.session_allows: set[str] = set()

    def register(self, approval_id: str) -> "asyncio.Future[str]":
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self.pending[approval_id] = fut
        return fut

    def resolve(self, approval_id: str, decision: str) -> bool:
        """Deliver a decision to a pending approval future. Returns True if found."""
        fut = self.pending.pop(approval_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(decision)
        return True


@dataclass(slots=True)
class PermissionPolicy:
    deny_all_by_default: bool
    allow_network: bool
    allowed_paths: list[Path]
    allowed_tool_names: set[str]
    blocked_tool_names: set[str]
    allowed_command_prefixes: list[str]
    workspace_root: Path = field(default_factory=lambda: Path(".").resolve())
    permission_rules: list[PermissionRule] = field(default_factory=list)
    doom_loop_action: str = "deny"          # "deny" | "ask"
    doom_loop_invalid_threshold: int = 3    # repeated_invalid_count limit
    doom_loop_no_progress_threshold: int = 6  # consecutive_no_progress_steps limit

    @classmethod
    def from_config(cls, cfg: ConfigManager, workspace_root: Path) -> "PermissionPolicy":
        raw_paths = cfg.get("tools.allowed_paths", []) or []
        resolved = [workspace_root / p for p in raw_paths]
        raw_rules = cfg.get("tools.permission_rules", []) or []
        parsed_rules: list[PermissionRule] = []
        for row in raw_rules:
            if not isinstance(row, dict):
                continue
            permission = str(row.get("permission") or "").strip().lower()
            pattern = str(row.get("pattern") or "").strip()
            action = str(row.get("action") or "").strip().lower()
            if not permission or not pattern or action not in {"allow", "ask", "deny"}:
                continue
            parsed_rules.append(PermissionRule(permission=permission, pattern=pattern, action=action))
        raw_dl_action = str(cfg.get("tools.doom_loop_action", "deny") or "deny").strip().lower()
        doom_loop_action = raw_dl_action if raw_dl_action in {"deny", "ask"} else "deny"
        return cls(
            deny_all_by_default=bool(cfg.get("tools.deny_all_by_default", True)),
            allow_network=bool(cfg.get("tools.allow_network", False)),
            allowed_paths=resolved,
            allowed_tool_names=set(cfg.get("tools.allowed_tool_names", []) or []),
            blocked_tool_names=set(cfg.get("tools.blocked_tool_names", []) or []),
            allowed_command_prefixes=list(cfg.get("tools.allowed_command_prefixes", []) or []),
            workspace_root=workspace_root.resolve(),
            permission_rules=parsed_rules,
            doom_loop_action=doom_loop_action,
            doom_loop_invalid_threshold=int(cfg.get("tools.doom_loop_invalid_threshold", 3)),
            doom_loop_no_progress_threshold=int(cfg.get("tools.doom_loop_no_progress_threshold", 6)),
        )

    def _normalize_path(self, raw_path: str) -> Path:
        candidate = Path(str(raw_path))
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.workspace_root / candidate).resolve()

    def _path_variants(self, raw_path: str) -> set[str]:
        path = self._normalize_path(raw_path)
        variants = {path.as_posix()}
        try:
            rel = path.relative_to(self.workspace_root)
            variants.add(rel.as_posix())
        except ValueError:
            pass
        return variants

    def _collect_path_values(self, tool: ToolDefinition, args: dict[str, Any], *, include_required: bool = True) -> set[str]:
        path_values: set[str] = set()
        path_keys = ["path", "target_path", "directory_path", "source_path", "destination_path", "file_path"]
        capabilities = tool.capabilities or []
        is_http_tool = any(cap.startswith("http.") or cap == "api.request" for cap in capabilities)
        if is_http_tool:
            path_keys = [k for k in path_keys if k != "path"]

        for key in path_keys:
            value = args.get(key)
            if not value:
                continue
            path_values.update(self._path_variants(str(value)))

        if include_required:
            for required in tool.required_paths:
                if not required:
                    continue
                path_values.update(self._path_variants(str(required)))

        return path_values

    def _resolve_permission_domain(self, tool: ToolDefinition, args: dict[str, Any]) -> str:
        name = tool.name.lower()
        caps = tool.capabilities or []
        has_command = bool(str(args.get("command", "")).strip()) or bool(tool.required_commands)

        if has_command or any(cap in ("shell.exec", "shell.command", "process.exec") for cap in caps) or name in {
            "shell_command",
            "run_tests",
            "run_project_check",
            "lint_and_fix",
            "install_dependencies",
            "version_bump",
            "tag_and_publish_release",
            "generate_release_notes",
        }:
            return "bash"

        if tool.needs_network or name in {"web_fetch", "web_browse"}:
            return "webfetch"

        edit_tools = {
            "create_directory",
            "write_file",
            "append_file",
            "replace_in_file",
            "edit_file",
            "json_edit",
            "insert_at_line",
            "delete_range",
            "yaml_edit",
            "patch_file",
            "rename_or_move",
            "delete_file",
        }
        if name in edit_tools:
            return "edit"

        read_tools = {
            "read_file",
            "list_directory",
            "search_workspace",
            "read_context",
            "index_project",
            "propose_wiring",
        }
        if name in read_tools:
            return "read"

        return name

    def _evaluate_permission_rules(self, tool: ToolDefinition, args: dict[str, Any]) -> tuple[str | None, str | None]:
        if not self.permission_rules:
            return None, None

        permission = self._resolve_permission_domain(tool, args)
        if permission == "bash":
            candidates = {str(args.get("command", "")).strip()} if str(args.get("command", "")).strip() else set()
            candidates.update(str(cmd).strip() for cmd in tool.required_commands if str(cmd).strip())
            if not candidates:
                candidates = {"*"}
        elif permission in {"read", "edit"}:
            candidates = self._collect_path_values(tool, args)
            if not candidates:
                candidates = {"*"}
        else:
            candidates = {"*", tool.name}

        matched_action: str | None = None
        matched_pattern: str | None = None
        for rule in self.permission_rules:
            if rule.permission not in {permission, "*"}:
                continue
            if any(fnmatch.fnmatch(candidate, rule.pattern) for candidate in candidates):
                matched_action = rule.action
                matched_pattern = rule.pattern

        if matched_action is None:
            return None, None
        return matched_action, f"{permission}:{matched_pattern}"

    def evaluate_tool(self, tool: ToolDefinition, args: dict[str, Any]) -> tuple[bool, str]:
        if tool.name in self.blocked_tool_names:
            return False, "blocked_tool_name"

        rule_action, rule_match = self._evaluate_permission_rules(tool, args)
        if rule_action == "deny":
            return False, f"permission_rule_denied:{rule_match}"
        if rule_action == "ask":
            return False, f"approval_required:{rule_match}"
        allowed_by_rule = rule_action == "allow"

        if self.deny_all_by_default and not allowed_by_rule:
            if tool.name not in self.allowed_tool_names:
                return False, "tool_not_in_allowlist"

        if tool.needs_network and not self.allow_network:
            return False, "network_not_allowed"

        required_paths = self._collect_path_values(tool, args, include_required=True)
        for required in required_paths:
            if required == "*":
                continue
            req_path = self._normalize_path(required)
            # External-directory check: flag paths that escape the workspace root
            try:
                req_path.relative_to(self.workspace_root)
            except ValueError:
                if not any(str(req_path).startswith(str(base.resolve())) for base in self.allowed_paths):
                    return False, f"external_directory:{req_path.as_posix()}"
            if not any(str(req_path).startswith(str(base.resolve())) for base in self.allowed_paths):
                return False, "required_path_not_allowed"

        arg_paths = self._collect_path_values(tool, args, include_required=False)
        for arg_value in arg_paths:
            if arg_value == "*":
                continue
            req_path = self._normalize_path(arg_value)
            # External-directory check: flag paths that escape the workspace root
            try:
                req_path.relative_to(self.workspace_root)
            except ValueError:
                if not any(str(req_path).startswith(str(base.resolve())) for base in self.allowed_paths):
                    return False, f"external_directory:{req_path.as_posix()}"
            if not any(str(req_path).startswith(str(base.resolve())) for base in self.allowed_paths):
                return False, "argument_path_not_allowed"

        if tool.required_commands:
            for cmd in tool.required_commands:
                if not any(cmd.startswith(prefix) for prefix in self.allowed_command_prefixes):
                    return False, "required_command_not_allowed"

        command = str(args.get("command", "")).strip()
        if command:
            if not self.allowed_command_prefixes:
                return False, "commands_not_allowed"
            if not any(command.startswith(prefix) for prefix in self.allowed_command_prefixes):
                return False, "command_prefix_not_allowed"

        return True, "allowed"

class ToolRegistry:
    def __init__(
        self,
        policy: PermissionPolicy,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        max_concurrent_shell_evals: int = 2,
        max_concurrent_browser_sessions: int = 1,
    ) -> None:
        self.policy = policy
        self._tools: dict[str, ToolDefinition] = {}
        self._audit_sink = audit_sink
        self._hooks: ApiHooks | None = None
        self._rollback_store: Any | None = None  # RollbackStore — set after construction
        self.approval_store = ApprovalStore()
        # Per-category concurrency caps
        self._shell_semaphore = asyncio.Semaphore(max(1, max_concurrent_shell_evals))
        self._browser_semaphore = asyncio.Semaphore(max(1, max_concurrent_browser_sessions))

    def set_hooks(self, hooks: ApiHooks) -> None:
        self._hooks = hooks

    def set_rollback_store(self, store: Any) -> None:
        """Wire in a RollbackStore so file mutations are snapshotted before execution."""
        self._rollback_store = store

    def register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def unregister_tool(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return [self._tools[k] for k in sorted(self._tools.keys())]

    def search_tools(self, query: str) -> list[ToolDefinition]:
        q = query.lower()
        return [
            t
            for t in self._tools.values()
            if q in t.name.lower() or q in t.description.lower()
        ]

    def preview_policy(self, tool: ToolDefinition) -> tuple[bool, str]:
        """Policy preview with empty args for UI/API listing."""
        return self.policy.evaluate_tool(tool, {})

    async def _request_approval(
        self,
        tool: ToolDefinition,
        args: dict[str, Any],
        match_label: str,
        task_id: str | None,
    ) -> tuple[bool, str]:
        """Emit an approval_request stream event and suspend until the user responds.

        Returns (True, reason) on once/always grants, (False, reason) on reject/timeout.
        """
        approval_id = f"approval-{uuid.uuid4().hex[:12]}"
        if self._hooks is not None:
            await self._hooks.emit(
                HookPayload(
                    event="StreamEvent",
                    data={
                        "task_id": task_id or "",
                        "event_type": "approval_request",
                        "approval_id": approval_id,
                        "tool": tool.name,
                        "match_label": match_label,
                        "message": f"Tool '{tool.name}' requires approval ({match_label})",
                    },
                )
            )
        fut = self.approval_store.register(approval_id)
        try:
            decision = await asyncio.wait_for(asyncio.shield(fut), timeout=120.0)
        except asyncio.TimeoutError:
            self.approval_store.pending.pop(approval_id, None)
            return False, f"approval_timeout:{match_label}"
        if decision == "reject":
            return False, f"approval_rejected:{match_label}"
        if decision == "always":
            self.approval_store.session_allows.add(match_label)
        return True, f"approval_granted:{match_label}"

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        bypass_policy: bool = False,
        task_id: str | None = None,
        hook_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool = self.get_tool(name)
        if tool is None:
            self._emit_audit(name=name, status="denied", reason="tool_not_found", args=args)
            raise KeyError(f"Tool not found: {name}")

        effective_args = dict(args)
        tenant_id = str((hook_context or {}).get("tenant_id", "_system_"))
        call_index = int((hook_context or {}).get("call_index", 0))
        hook_payload = {
            "task_id": task_id or "",
            "tenant_id": tenant_id,
            "tool_name": name,
            "tool_args": dict(effective_args),
            "call_index": call_index,
            "allowed_tools": list((hook_context or {}).get("allowed_tools", []) or []),
        }
        if self._hooks is not None:
            directives = await self._hooks.execute("PreToolUse", hook_payload)
            for directive in directives:
                if not isinstance(directive, dict):
                    continue
                action = str(directive.get("action", "")).strip().lower()
                if action == "replace_args" and isinstance(directive.get("modified_args"), dict):
                    effective_args = dict(directive["modified_args"])
                if action == "abort":
                    message = str(directive.get("error_message") or "Tool call blocked by hook")
                    self._emit_audit(name=name, status="denied", reason="hook_aborted", args=effective_args)
                    return {
                        "ok": False,
                        "error": message,
                        "aborted_by_hook": True,
                        "tool": name,
                    }

        # Skip policy checks if bypass_policy is True (e.g., superpowered mode with approvals)
        if not bypass_policy:
            allowed, reason = self.policy.evaluate_tool(tool, effective_args)
            if not allowed:
                if reason.startswith("approval_required:"):
                    match_label = reason[len("approval_required:"):]
                    if match_label in self.approval_store.session_allows:
                        allowed = True
                        reason = f"session_approved:{match_label}"
                    else:
                        allowed, reason = await self._request_approval(
                            tool=tool, args=effective_args, match_label=match_label, task_id=task_id
                        )
                if not allowed:
                    self._emit_audit(name=name, status="denied", reason=reason, args=effective_args)
                    # Emit a guardrail stream event for external-directory violations so the
                    # live SSE timeline surfaces the block immediately.
                    if reason.startswith("external_directory:") and self._hooks is not None:
                        try:
                            await self._hooks.emit(
                                HookPayload(
                                    event="StreamEvent",
                                    data={
                                        "task_id": task_id or "",
                                        "event_type": "guardrail",
                                        "reason_code": "external_directory",
                                        "message": f"Tool '{name}' blocked: path outside workspace ({reason})",
                                        "tool": name,
                                        "path": reason[len("external_directory:"):],
                                    },
                                )
                            )
                        except Exception:
                            pass
                    raise PermissionError(f"Tool blocked by policy: {name} ({reason})")
        else:
            reason = "bypassed_for_superpowered_mode"

        # Snapshot files before mutation so they can be rolled back.
        if task_id and self._rollback_store is not None:
            from harness.runtime.rollback import MUTATING_TOOLS
            from pathlib import Path as _Path
            if name in MUTATING_TOOLS:
                for path_key in ("path", "source_path", "target_path"):
                    raw_path = effective_args.get(path_key)
                    if raw_path:
                        try:
                            self._rollback_store.snapshot(task_id, _Path(str(raw_path)))
                        except Exception:
                            pass  # Snapshot failure must never block execution.

        if tool.handler is None:
            self._emit_audit(name=name, status="allowed", reason="no_handler", args=effective_args)
            return {"ok": True, "message": f"Tool {name} has no handler in phase 1"}

        self._emit_audit(name=name, status="allowed", reason=reason, args=effective_args)

        # Enforce per-category concurrency caps
        caps = tool.capabilities or []
        is_shell = any(c in caps for c in ("shell.exec", "shell.command", "process.exec")) or \
                   name in ("shell_command", "run_tests", "run_project_check", "lint_and_fix",
                            "install_dependencies", "version_bump", "tag_and_publish_release")
        is_browser = any(c.startswith("browser.") for c in caps) or \
                     name in ("browser_action",)

        started_at = datetime.now(timezone.utc)
        error_message: str | None = None
        result: dict[str, Any]
        try:
            if is_shell:
                async with self._shell_semaphore:
                    result = await tool.handler(effective_args)
            elif is_browser:
                async with self._browser_semaphore:
                    result = await tool.handler(effective_args)
            else:
                result = await tool.handler(effective_args)
        except Exception as exc:
            error_message = str(exc)
            result = {"ok": False, "error": error_message}
            raise
        finally:
            if self._hooks is not None:
                duration_ms = (datetime.now(timezone.utc) - started_at).total_seconds() * 1000.0
                await self._hooks.emit(
                    HookPayload(
                        event="PostToolUse",
                        data={
                            "task_id": task_id or "",
                            "tenant_id": tenant_id,
                            "tool_name": name,
                            "tool_args": dict(effective_args),
                            "result": result,
                            "error": error_message,
                            "duration_ms": duration_ms,
                            "call_index": call_index,
                        },
                    )
                )
        return result

    def find_tools_by_capability(self, capability: str) -> list[ToolDefinition]:
        """Find all tools that have a specific capability."""
        return [
            t for t in self._tools.values()
            if capability in (t.capabilities or [])
        ]

    def rank_tools_for_capabilities(
        self,
        required_capabilities: list[str] | None = None,
    ) -> list[tuple[ToolDefinition, float]]:
        """
        Rank all available tools by how well they match required capabilities.
        Returns list of (tool, score) tuples sorted by score (highest first).
        """

        if not required_capabilities:
            required_capabilities = []

        scores = [
            (tool, 1.0)
            for tool in self._tools.values()
        ]

        # Filter out blocked tools (score 0)
        viable = [(t, s) for t, s in scores if s > 0]

        # If no viable tools, return all (for debugging/transparency)
        if not viable:
            return sorted(scores, key=lambda x: x[1], reverse=True)

        return sorted(viable, key=lambda x: x[1], reverse=True)

    def select_best_tool(
        self,
        required_capabilities: list[str] | None = None,
    ) -> ToolDefinition | None:
        """
        Select the best-scoring tool that matches required capabilities.
        Returns None if no viable tools available.
        """
        ranked = self.rank_tools_for_capabilities(required_capabilities)
        if ranked:
            return ranked[0][0]
        return None

    def _emit_audit(self, name: str, status: str, reason: str, args: dict[str, Any]) -> None:
        if self._audit_sink is None:
            return
        self._audit_sink(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": name,
                "status": status,
                "reason": reason,
                "arg_keys": sorted(list(args.keys())),
            }
        )
