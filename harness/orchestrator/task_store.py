from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from harness.runtime.types import Task, TaskResult


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    description: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    success: bool | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class TaskStore:
    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    def create(self, task: Task) -> TaskRecord:
        record = TaskRecord(
            task_id=task.id,
            description=task.description,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[task.id] = record
        return record

    def mark_started(self, task_id: str) -> None:
        record = self._records[task_id]
        record.status = "running"
        record.started_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self, result: TaskResult) -> None:
        record = self._records[result.task_id]
        record.status = "completed" if result.success else "failed"
        record.completed_at = datetime.now(timezone.utc).isoformat()
        record.success = result.success
        record.output = result.output
        record.error = result.error

    def list(self) -> list[TaskRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)
