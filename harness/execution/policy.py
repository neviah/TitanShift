from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.runtime.config import ConfigManager


@dataclass(slots=True)
class ExecutionPolicy:
    allowed_cwd_roots: list[Path]
    allowed_command_prefixes: list[str]
    max_runtime_s: int
    max_output_bytes: int

    @classmethod
    def from_config(cls, cfg: ConfigManager, workspace_root: Path) -> "ExecutionPolicy":
        roots = cfg.get("execution.allowed_cwd_roots", ["."]) or ["."]
        return cls(
            allowed_cwd_roots=[(workspace_root / r).resolve() for r in roots],
            allowed_command_prefixes=list(cfg.get("execution.allowed_command_prefixes", []) or []),
            max_runtime_s=int(cfg.get("execution.max_runtime_s", 30)),
            max_output_bytes=int(cfg.get("execution.max_output_bytes", 32768)),
        )

    def is_command_allowed(self, command: str) -> bool:
        if not self.allowed_command_prefixes:
            return False
        return any(command.startswith(prefix) for prefix in self.allowed_command_prefixes)

    def is_cwd_allowed(self, cwd: Path) -> bool:
        target = cwd.resolve()
        return any(str(target).startswith(str(base)) for base in self.allowed_cwd_roots)
