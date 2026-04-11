from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.task_store import TaskStore
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.types import Task, TaskResult
from harness.skills.registry import SkillRegistry
from harness.state_machine.reactive import ReactiveStateMachine
from harness.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentRecord:
    agent_id: str
    role: str
    assigned_skills: list[str]
    allowed_tools: list[str]
    model_backend: str
    spawned_from_task: str | None
    created_at: str
    active: bool = True


@dataclass(slots=True)
class Orchestrator:
    config: ConfigManager
    event_bus: EventBus
    memory: MemoryManager
    models: ModelRegistry
    skills: SkillRegistry
    tools: ToolRegistry
    state_machine: ReactiveStateMachine = field(init=False)
    enable_subagents: bool = field(init=False)
    task_store: TaskStore = field(init=False)
    agents: dict[str, AgentRecord] = field(init=False)

    def __post_init__(self) -> None:
        self.state_machine = ReactiveStateMachine(self.models, self.config)
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        self.task_store = TaskStore()
        self.agents = {
            "main-agent": AgentRecord(
                agent_id="main-agent",
                role=str(self.config.get("orchestrator.default_role", "General Agent")),
                assigned_skills=["reactive_chat"],
                allowed_tools=[],
                model_backend=str(self.config.get("model.default_backend", "local_stub")),
                spawned_from_task=None,
                created_at=datetime.now(timezone.utc).isoformat(),
                active=True,
            )
        }

    async def run_reactive_task(self, task: Task) -> TaskResult:
        self.task_store.create(task)
        self.task_store.mark_started(task.id)
        await self.event_bus.publish("AGENT_SPAWNED", {"task_id": task.id, "subagents": False})
        self.memory.append_short_term("main-agent", {"task": task.description})
        try:
            result = await self.state_machine.run_task(task)
        except Exception as exc:
            await self.event_bus.publish(
                "MODULE_ERROR",
                {
                    "source": "orchestrator",
                    "task_id": task.id,
                    "error": str(exc),
                },
            )
            result = TaskResult(task_id=task.id, output={}, success=False, error=f"Unhandled runtime error: {exc}")
        self.task_store.mark_completed(result)
        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
        return result

    async def spawn_subagent(self, _task: Task) -> str:
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        if not self.enable_subagents:
            raise RuntimeError("Sub-agent spawning is disabled by config toggle")

        role = str(_task.input.get("role", "Specialist Agent"))
        backend = str(_task.input.get("model_backend", self.config.get("model.default_backend", "local_stub")))
        skill_matches = self.skills.search_skills(_task.description)[:3]
        assigned_skills = [s.skill_id for s in skill_matches] or ["reactive_chat"]
        allowed_tools = sorted({tool for s in skill_matches for tool in s.required_tools})

        agent_id = f"subagent-{uuid.uuid4().hex[:8]}"
        self.agents[agent_id] = AgentRecord(
            agent_id=agent_id,
            role=role,
            assigned_skills=assigned_skills,
            allowed_tools=allowed_tools,
            model_backend=backend,
            spawned_from_task=_task.id,
            created_at=datetime.now(timezone.utc).isoformat(),
            active=True,
        )
        self.memory.append_short_term(agent_id, {"spawned_from": _task.id, "role": role})
        await self.event_bus.publish(
            "AGENT_SPAWNED",
            {"task_id": _task.id, "subagents": True, "agent_id": agent_id, "role": role},
        )
        return agent_id

    def list_agents(self) -> list[dict]:
        return [asdict(r) for r in sorted(self.agents.values(), key=lambda x: x.created_at)]

    def list_tasks(self) -> list[dict]:
        return [asdict(record) for record in self.task_store.list()]

    def get_task(self, task_id: str) -> dict | None:
        record = self.task_store.get(task_id)
        return None if record is None else asdict(record)
