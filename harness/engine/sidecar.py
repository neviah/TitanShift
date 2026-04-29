from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
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

    @staticmethod
    def _extract_prompt_paths(prompt: str) -> list[str]:
        """Extract likely workspace file paths from a natural-language prompt."""
        if not prompt:
            return []
        # Keep this conservative: only capture file-like tokens with an extension.
        pattern = re.compile(r"(?<![\w/.-])([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+)(?![\w/.-])")
        out: list[str] = []
        seen: set[str] = set()
        for raw in pattern.findall(prompt):
            candidate = raw.strip().strip("'\"").replace("\\", "/")
            if not candidate or candidate.lower().startswith(("http://", "https://")):
                continue
            if ".." in candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
        return out[:12]

    @staticmethod
    def _hash_file(path: Path) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    @classmethod
    def _snapshot_targets(cls, cwd: Path, rel_paths: list[str]) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for rel_path in rel_paths:
            target = (cwd / rel_path).resolve()
            try:
                target.relative_to(cwd.resolve())
            except Exception:
                continue
            snapshot[str(rel_path).replace("\\", "/")] = cls._hash_file(target)
        return snapshot

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

        prompt_text = str(payload.get("prompt") or "")
        candidate_paths = self._extract_prompt_paths(prompt_text)
        before_snapshot = self._snapshot_targets(cwd, candidate_paths)

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

        def _parse_json_dict(raw: str) -> dict[str, Any]:
            if not raw:
                return {}
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass

            # Some sidecars/loggers prepend lines before the final JSON payload.
            for line in reversed(raw.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded = json.loads(line)
                    if isinstance(loaded, dict):
                        return loaded
                except Exception:
                    continue
            return {}

        parsed: dict[str, Any] = _parse_json_dict(stdout_text)

        response_text = ""
        for key in ("response", "text", "message", "content"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                response_text = value.strip()
                break
        if not response_text:
            response_text = stdout_text
        success_flag = bool(parsed.get("success", process.returncode == 0))
        error_value = parsed.get("error")
        error_text = error_value.strip() if isinstance(error_value, str) else None

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

        # Sidecar CLIs may omit structured file evidence. Infer it from prompt-targeted files.
        inferred_created: list[str] = []
        inferred_updated: list[str] = []
        if before_snapshot:
            after_snapshot = self._snapshot_targets(cwd, list(before_snapshot.keys()))
            for rel_path, before_hash in before_snapshot.items():
                after_hash = after_snapshot.get(rel_path)
                if before_hash is None and after_hash is not None:
                    inferred_created.append(rel_path)
                elif before_hash is not None and after_hash is not None and before_hash != after_hash:
                    inferred_updated.append(rel_path)

        if inferred_created:
            created_paths = list(dict.fromkeys([*created_paths, *inferred_created]))
        if inferred_updated:
            updated_paths = list(dict.fromkeys([*updated_paths, *inferred_updated]))

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
