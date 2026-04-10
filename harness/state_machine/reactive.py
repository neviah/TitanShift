from __future__ import annotations

from harness.model.adapter import ModelRegistry, ModelRequest
from harness.runtime.types import Task, TaskResult


class ReactiveStateMachine:
    """Phase 1 reactive loop: single pass plan-act-reflect shape."""

    def __init__(self, models: ModelRegistry) -> None:
        self.models = models

    async def run_task(self, task: Task) -> TaskResult:
        preferred_backend = task.input.get("model_backend") if task.input else None
        model = self.models.select_model(preferred_backend)
        response = await model.generate(ModelRequest(prompt=task.description))
        return TaskResult(
            task_id=task.id,
            output={
                "response": response.text,
                "model": response.model_id,
                "mode": "reactive",
            },
            success=True,
        )
