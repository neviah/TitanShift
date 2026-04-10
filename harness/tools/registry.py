from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.runtime.config import ConfigManager
from harness.tools.definitions import ToolDefinition


@dataclass(slots=True)
class PermissionPolicy:
    deny_all_by_default: bool
    allow_network: bool
    allowed_paths: list[Path]

    @classmethod
    def from_config(cls, cfg: ConfigManager, workspace_root: Path) -> "PermissionPolicy":
        raw_paths = cfg.get("tools.allowed_paths", []) or []
        resolved = [workspace_root / p for p in raw_paths]
        return cls(
            deny_all_by_default=bool(cfg.get("tools.deny_all_by_default", True)),
            allow_network=bool(cfg.get("tools.allow_network", False)),
            allowed_paths=resolved,
        )

    def allows_tool(self, tool: ToolDefinition) -> bool:
        if not self.deny_all_by_default:
            return True
        if tool.needs_network and not self.allow_network:
            return False
        for required in tool.required_paths:
            if not any(str(required).startswith(str(base)) for base in self.allowed_paths):
                return False
        return True


class ToolRegistry:
    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy
        self._tools: dict[str, ToolDefinition] = {}

    def register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    async def execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.get_tool(name)
        if tool is None:
            raise KeyError(f"Tool not found: {name}")
        if not self.policy.allows_tool(tool):
            raise PermissionError(f"Tool blocked by deny-all policy: {name}")
        if tool.handler is None:
            return {"ok": True, "message": f"Tool {name} has no handler in phase 1"}
        return await tool.handler(args)
