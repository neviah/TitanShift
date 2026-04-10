from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from harness.api.hooks import ApiHooks, HookPayload
from harness.api.schemas import ChatRequest, ChatResponse
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.orchestrator import Orchestrator
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.types import Task
from harness.tools.registry import PermissionPolicy, ToolRegistry


@dataclass(slots=True)
class RuntimeContainer:
    config: ConfigManager
    event_bus: EventBus
    memory: MemoryManager
    models: ModelRegistry
    tools: ToolRegistry
    orchestrator: Orchestrator
    hooks: ApiHooks


def create_runtime(workspace_root: Path) -> RuntimeContainer:
    cfg = ConfigManager(workspace_root)
    bus = EventBus()
    memory = MemoryManager(cfg, workspace_root)
    models = ModelRegistry.from_config(cfg)
    tools = ToolRegistry(PermissionPolicy.from_config(cfg, workspace_root))
    orchestrator = Orchestrator(config=cfg, event_bus=bus, memory=memory, models=models, tools=tools)
    hooks = ApiHooks()

    async def on_agent_spawned(payload: dict) -> None:
        await hooks.emit(HookPayload(event="AGENT_SPAWNED", data=payload))

    async def on_task_completed(payload: dict) -> None:
        await hooks.emit(HookPayload(event="TASK_COMPLETED", data=payload))

    bus.subscribe("AGENT_SPAWNED", on_agent_spawned)
    bus.subscribe("TASK_COMPLETED", on_task_completed)
    return RuntimeContainer(cfg, bus, memory, models, tools, orchestrator, hooks)


def create_app(workspace_root: Path) -> FastAPI:
    runtime = create_runtime(workspace_root)
    app = FastAPI(title="TitantShift Harness API", version="0.1.0")

    @app.get("/status")
    async def status() -> dict:
        return {
            "ok": True,
            "subagents_enabled": runtime.config.get("orchestrator.enable_subagents"),
            "graph_backend": runtime.config.get("memory.graph_backend"),
            "semantic_backend": runtime.config.get("memory.semantic_backend"),
            "default_model_backend": runtime.config.get("model.default_backend"),
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest) -> ChatResponse:
        task = Task(
            id=str(uuid.uuid4()),
            description=body.prompt,
            input={"model_backend": body.model_backend} if body.model_backend else {},
        )
        result = await runtime.orchestrator.run_reactive_task(task)
        return ChatResponse(
            response=result.output.get("response", ""),
            model=result.output.get("model", "unknown"),
            mode=result.output.get("mode", "reactive"),
        )

    return app
