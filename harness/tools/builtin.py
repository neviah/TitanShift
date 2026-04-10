from __future__ import annotations

import shlex
from typing import Any

from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry


def register_builtin_tools(tools: ToolRegistry, execution: ExecutionModule) -> None:
    async def shell_command_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("command", "")).strip()
        if not raw:
            raise ValueError("command is required")

        parts = shlex.split(raw, posix=False)
        command = parts[0]
        command_args = [str(p) for p in parts[1:]]
        try:
            result = await execution.run_command(command, *command_args, cwd=args.get("cwd"))
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="shell_command",
            description="Run shell commands through policy-constrained execution module",
            handler=shell_command_handler,
        )
    )
