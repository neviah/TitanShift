from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from harness.execution.policy import ExecutionPolicy


@dataclass(slots=True)
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool = False


class ExecutionDeniedError(RuntimeError):
    pass


class ExecutionModule:
    def __init__(self, policy: ExecutionPolicy, default_cwd: Path) -> None:
        self.policy = policy
        self.default_cwd = default_cwd.resolve()

    def _build_env(self) -> dict[str, str] | None:
        """Return a filtered environment dict when sandbox_env is enabled."""
        if not self.policy.sandbox_env:
            return None
        allowed = set(self.policy.allowed_env_vars)
        return {k: v for k, v in os.environ.items() if k in allowed}

    async def run_command(
        self,
        command: str,
        *args: str,
        timeout_s: int | None = None,
        cwd: str | None = None,
    ) -> ExecutionResult:
        if not self.policy.is_command_allowed(command):
            raise ExecutionDeniedError(f"Command blocked by execution policy: {command}")

        run_cwd = (Path(cwd).resolve() if cwd else self.default_cwd)
        if not self.policy.is_cwd_allowed(run_cwd):
            raise ExecutionDeniedError(f"CWD blocked by execution policy: {run_cwd}")

        effective_timeout = timeout_s if timeout_s is not None else self.policy.max_runtime_s
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=str(run_cwd),
            env=self._build_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
        max_bytes = self.policy.max_output_bytes
        truncated = False
        if len(stdout_b) > max_bytes:
            stdout_b = stdout_b[:max_bytes]
            truncated = True
        if len(stderr_b) > max_bytes:
            stderr_b = stderr_b[:max_bytes]
            truncated = True

        return ExecutionResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            truncated=truncated,
        )
