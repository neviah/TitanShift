from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SidecarExecutionResult:
    success: bool
    response: str
    model: str
    provider_model: str | None
    engine: str
    error: str | None = None
    used_tools: list[str] | None = None
    created_paths: list[str] | None = None
    updated_paths: list[str] | None = None
    artifacts: list[dict[str, Any]] | None = None
    raw_output: str = ""
    stderr: str = ""


class SidecarProcessAdapter:
    """Run a sidecar command for one task invocation.

    The command receives a JSON payload on stdin and should return JSON on stdout.
    If stdout is not JSON, it is treated as plain text response.
    """

    def __init__(
        self,
        *,
        engine_name: str,
        command: list[str],
        timeout_s: float,
        shared_env: dict[str, str] | None = None,
    ) -> None:
        self.engine_name = engine_name
        self.command = [c for c in command if str(c).strip()]
        self.timeout_s = max(1.0, float(timeout_s or 1.0))
        self.shared_env = shared_env or {}

    @staticmethod
    def parse_command(raw: Any) -> list[str]:
        if isinstance(raw, list):
            return [str(part).strip() for part in raw if str(part).strip()]
        if isinstance(raw, str) and raw.strip():
            return [part for part in shlex.split(raw) if part.strip()]
        return []

    async def run(self, *, payload: dict[str, Any], cwd: Path) -> SidecarExecutionResult:
        if not self.command:
            return SidecarExecutionResult(
                success=False,
                response="",
                model="sidecar",
                provider_model=None,
                engine=self.engine_name,
                error=(
                    f"{self.engine_name} sidecar command is not configured. "
                    "Set engine.sidecar.<mode>.command in harness.config.json"
                ),
            )

        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in self.shared_env.items()})
        payload_bytes = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")

        process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=payload_bytes),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return SidecarExecutionResult(
                success=False,
                response="",
                model="sidecar",
                provider_model=None,
                engine=self.engine_name,
                error=f"{self.engine_name} sidecar timed out after {self.timeout_s:.1f}s",
            )

        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

        parsed: dict[str, Any] = {}
        if stdout_text:
            try:
                loaded = json.loads(stdout_text)
                if isinstance(loaded, dict):
                    parsed = loaded
            except Exception:
                parsed = {}

        response_text = str(parsed.get("response") or parsed.get("text") or stdout_text)
        success_flag = bool(parsed.get("success", process.returncode == 0))
        error_text = str(parsed.get("error") or "").strip() or None

        if not success_flag and error_text is None and stderr_text:
            error_text = stderr_text[:2000]

        used_tools_raw = parsed.get("used_tools")
        used_tools = [str(t) for t in used_tools_raw if isinstance(t, str)] if isinstance(used_tools_raw, list) else []

        created_paths_raw = parsed.get("created_paths")
        created_paths = [str(p) for p in created_paths_raw if isinstance(p, str)] if isinstance(created_paths_raw, list) else []

        updated_paths_raw = parsed.get("updated_paths")
        updated_paths = [str(p) for p in updated_paths_raw if isinstance(p, str)] if isinstance(updated_paths_raw, list) else []

        artifacts_raw = parsed.get("artifacts")
        artifacts = [item for item in artifacts_raw if isinstance(item, dict)] if isinstance(artifacts_raw, list) else []

        return SidecarExecutionResult(
            success=success_flag,
            response=response_text,
            model=str(parsed.get("model") or "sidecar"),
            provider_model=(str(parsed.get("provider_model")) if parsed.get("provider_model") else None),
            engine=self.engine_name,
            error=error_text,
            used_tools=used_tools,
            created_paths=created_paths,
            updated_paths=updated_paths,
            artifacts=artifacts,
            raw_output=stdout_text,
            stderr=stderr_text,
        )
