from __future__ import annotations

import asyncio

from harness.model.adapter import ModelRegistry, ModelRequest
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task, TaskResult


class ReactiveStateMachine:
    """Phase 1 reactive loop: single pass plan-act-reflect shape."""

    def __init__(self, models: ModelRegistry, config: ConfigManager) -> None:
        self.models = models
        self.config = config

    async def run_task(self, task: Task) -> TaskResult:
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: max_steps < 1")

        preferred_backend = task.input.get("model_backend") if task.input else None
        model = self.models.select_model(preferred_backend)

        prompt_tokens = model.estimate_tokens(task.description)
        if prompt_tokens > budget["max_tokens"]:
            return TaskResult(
                task_id=task.id,
                output={"prompt_tokens": prompt_tokens},
                success=False,
                error="Budget exceeded: prompt token estimate is above max_tokens",
            )

        try:
            response = await asyncio.wait_for(
                model.generate(ModelRequest(prompt=task.description)),
                timeout=budget["max_duration_ms"] / 1000.0,
            )
        except TimeoutError:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: task timeout")

        total_tokens = prompt_tokens + model.estimate_tokens(response.text)
        if total_tokens > budget["max_tokens"]:
            return TaskResult(
                task_id=task.id,
                output={
                    "response": response.text,
                    "model": response.model_id,
                    "mode": "reactive",
                    "estimated_total_tokens": total_tokens,
                },
                success=False,
                error="Budget exceeded: estimated total tokens above max_tokens",
            )

        return TaskResult(
            task_id=task.id,
            output={
                "response": response.text,
                "model": response.model_id,
                "mode": "reactive",
                "estimated_total_tokens": total_tokens,
            },
            success=True,
        )

    def _resolve_budget(self, task: Task) -> dict[str, int]:
        default_steps = int(self.config.get("state_machine.default_budget.max_steps", 1))
        default_tokens = int(self.config.get("state_machine.default_budget.max_tokens", 8192))
        default_duration = int(self.config.get("state_machine.default_budget.max_duration_ms", 60000))

        req_budget = task.input.get("budget", {}) if task.input else {}
        return {
            "max_steps": int(req_budget.get("max_steps", default_steps)),
            "max_tokens": int(req_budget.get("max_tokens", default_tokens)),
            "max_duration_ms": int(req_budget.get("max_duration_ms", default_duration)),
        }
