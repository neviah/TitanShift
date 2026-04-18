from __future__ import annotations

import asyncio


class CancellationRegistry:
    """Maps running task IDs to their asyncio.Task so they can be cancelled."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, task_id: str, task: asyncio.Task) -> None:
        self._tasks[task_id] = task

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task. Returns True if the task was found and cancelled."""
        task = self._tasks.pop(task_id, None)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    def unregister(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def is_running(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and not task.done()

    def running_task_ids(self) -> list[str]:
        return [tid for tid, t in self._tasks.items() if not t.done()]
