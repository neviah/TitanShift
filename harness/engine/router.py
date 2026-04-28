from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.engine.sidecar import SidecarExecutionResult, SidecarProcessAdapter
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task


class EngineRouter:
    """Routes task execution to configured sidecar engines."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def sidecar_enabled(self) -> bool:
        return bool(self.config.get("engine.use_sidecar", False))

    def _shared_env(self) -> dict[str, str]:
        raw = self.config.get("engine.sidecar.shared_env", {})
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if str(k).strip()}

    def _build_adapter(self, workflow_mode: str) -> SidecarProcessAdapter:
        mode_key = "superpowered" if workflow_mode == "superpowered" else "lightning"
        command_raw = self.config.get(f"engine.sidecar.{mode_key}.command", [])
        timeout_raw = self.config.get(f"engine.sidecar.{mode_key}.timeout_s", 1800)
        command = SidecarProcessAdapter.parse_command(command_raw)
        timeout_s = float(timeout_raw or 1800)
        engine_name = "openclaude" if mode_key == "superpowered" else "opencode"
        return SidecarProcessAdapter(
            engine_name=engine_name,
            command=command,
            timeout_s=timeout_s,
            shared_env=self._shared_env(),
        )

    async def run_task(self, task: Task, *, workflow_mode: str, workspace_root: Path) -> SidecarExecutionResult:
        adapter = self._build_adapter(workflow_mode)
        payload: dict[str, Any] = {
            "task_id": task.id,
            "prompt": task.description,
            "workflow_mode": workflow_mode,
            "workspace_root": str(workspace_root),
            "task_input": dict(task.input or {}),
            "model_backend": str(task.input.get("model_backend", "")) if task.input else "",
        }
        return await adapter.run(payload=payload, cwd=workspace_root)
