from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int


class ExecutionModule:
    async def run_command(self, command: str, *args: str, timeout_s: int = 30) -> ExecutionResult:
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return ExecutionResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
        )
