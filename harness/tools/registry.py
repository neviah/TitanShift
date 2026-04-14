from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from datetime import datetime, timezone

from harness.runtime.config import ConfigManager
from harness.tools.definitions import ToolDefinition


@dataclass(slots=True)
class PermissionPolicy:
    deny_all_by_default: bool
    allow_network: bool
    allowed_paths: list[Path]
    allowed_tool_names: set[str]
    blocked_tool_names: set[str]
    allowed_command_prefixes: list[str]

    @classmethod
    def from_config(cls, cfg: ConfigManager, workspace_root: Path) -> "PermissionPolicy":
        raw_paths = cfg.get("tools.allowed_paths", []) or []
        resolved = [workspace_root / p for p in raw_paths]
        return cls(
            deny_all_by_default=bool(cfg.get("tools.deny_all_by_default", True)),
            allow_network=bool(cfg.get("tools.allow_network", False)),
            allowed_paths=resolved,
            allowed_tool_names=set(cfg.get("tools.allowed_tool_names", []) or []),
            blocked_tool_names=set(cfg.get("tools.blocked_tool_names", []) or []),
            allowed_command_prefixes=list(cfg.get("tools.allowed_command_prefixes", []) or []),
        )

    def evaluate_tool(self, tool: ToolDefinition, args: dict[str, Any]) -> tuple[bool, str]:
        if tool.name in self.blocked_tool_names:
            return False, "blocked_tool_name"

        if self.deny_all_by_default:
            if tool.name not in self.allowed_tool_names:
                return False, "tool_not_in_allowlist"

        if tool.needs_network and not self.allow_network:
            return False, "network_not_allowed"

        for required in tool.required_paths:
            req = str((Path(required)).resolve())
            if not any(req.startswith(str(base.resolve())) for base in self.allowed_paths):
                return False, "required_path_not_allowed"

        for path_key in ["path", "target_path", "directory_path", "source_path", "destination_path"]:
            arg_path = args.get(path_key)
            if not arg_path:
                continue
            candidate = Path(str(arg_path))
            if candidate.is_absolute():
                req = str(candidate.resolve())
            elif self.allowed_paths:
                req = str((self.allowed_paths[0] / candidate).resolve())
            else:
                req = str(candidate.resolve())
            if not any(req.startswith(str(base.resolve())) for base in self.allowed_paths):
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
    ) -> None:
        self.policy = policy
        self._tools: dict[str, ToolDefinition] = {}
        self._audit_sink = audit_sink

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

    async def execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.get_tool(name)
        if tool is None:
            self._emit_audit(name=name, status="denied", reason="tool_not_found", args=args)
            raise KeyError(f"Tool not found: {name}")

        allowed, reason = self.policy.evaluate_tool(tool, args)
        if not allowed:
            self._emit_audit(name=name, status="denied", reason=reason, args=args)
            raise PermissionError(f"Tool blocked by deny-all policy: {name}")

        if tool.handler is None:
            self._emit_audit(name=name, status="allowed", reason="no_handler", args=args)
            return {"ok": True, "message": f"Tool {name} has no handler in phase 1"}

        self._emit_audit(name=name, status="allowed", reason=reason, args=args)
        return await tool.handler(args)

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
        from harness.tools.scoring import score_tool_for_task

        if not required_capabilities:
            required_capabilities = []

        scores = [
            (tool, score_tool_for_task(tool, required_capabilities).total_score)
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
