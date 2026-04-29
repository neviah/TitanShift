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

    def _shared_env(self, workflow_mode: str) -> dict[str, str]:
        raw = self.config.get("engine.sidecar.shared_env", {})
        user_env = {str(k): str(v) for k, v in raw.items() if str(k).strip()} if isinstance(raw, dict) else {}
        allow_model_fallback = bool(self.config.get("engine.sidecar.allow_model_fallback", False))

        base_url = str(self.config.get("model.openai_compatible.base_url", "") or "").strip()
        api_key = str(self.config.get("model.openai_compatible.api_key", "") or "").strip()
        shared_model = str(self.config.get("model.openai_compatible.model", "") or "").strip()
        if workflow_mode == "superpowered":
            mode_model = str(self.config.get("model.superpowered_model", "") or "").strip()
        else:
            mode_model = str(self.config.get("model.lightning_model", "") or "").strip()
        model = mode_model or shared_model

        derived: dict[str, str] = {
            # openclaude expects this for OpenAI-compatible routing.
            "CLAUDE_CODE_USE_OPENAI": "1",
            "OPENCLAUDE_PROVIDER": "openai",
        }
        if base_url:
            derived["OPENAI_BASE_URL"] = base_url
        if api_key:
            derived["OPENAI_API_KEY"] = api_key
            # OpenCode's OpenRouter provider loader expects this env var.
            derived["OPENROUTER_API_KEY"] = api_key
        if model:
            derived["OPENAI_MODEL"] = model
            derived["OPENROUTER_MODEL"] = model

        browse_backend = str(self.config.get("tools.web_browse_backend", "playwright") or "").strip().lower()
        if browse_backend in {"playwright", "obscura", "auto"}:
            derived["TITANSHIFT_WEB_BROWSE_BACKEND"] = browse_backend

        # Keep model selection explicit by default to avoid costly unintended provider defaults.
        derived["OPENCODE_ALLOW_MODEL_FALLBACK"] = "1" if allow_model_fallback else "0"

        # User-provided env overrides derived defaults.
        derived.update(user_env)
        return derived

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
            shared_env=self._shared_env(workflow_mode),
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
