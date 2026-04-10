from __future__ import annotations

from dataclasses import asdict, dataclass, field

from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.task_store import TaskStore
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.types import Task, TaskResult
from harness.state_machine.reactive import ReactiveStateMachine
from harness.tools.registry import ToolRegistry


@dataclass(slots=True)
class Orchestrator:
    config: ConfigManager
    event_bus: EventBus
    memory: MemoryManager
    models: ModelRegistry
    tools: ToolRegistry
    state_machine: ReactiveStateMachine = field(init=False)
    enable_subagents: bool = field(init=False)
    task_store: TaskStore = field(init=False)

    def __post_init__(self) -> None:
        self.state_machine = ReactiveStateMachine(self.models, self.config)
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        self.task_store = TaskStore()

    async def run_reactive_task(self, task: Task) -> TaskResult:
        self.task_store.create(task)
        self.task_store.mark_started(task.id)
        await self.event_bus.publish("AGENT_SPAWNED", {"task_id": task.id, "subagents": False})
        self.memory.append_short_term("main-agent", {"task": task.description})
        result = await self.state_machine.run_task(task)
        self.task_store.mark_completed(result)
        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
        return result

    async def spawn_subagent(self, _task: Task) -> str:
        if not self.enable_subagents:
            raise RuntimeError("Sub-agent spawning is disabled by config toggle")
        return "subagent-stub"

    def list_tasks(self) -> list[dict]:
        return [asdict(record) for record in self.task_store.list()]

    def get_task(self, task_id: str) -> dict | None:
        record = self.task_store.get(task_id)
        return None if record is None else asdict(record)
