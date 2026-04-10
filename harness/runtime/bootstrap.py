from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.api.hooks import ApiHooks, HookPayload
from harness.logging.logger import JsonLogger
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.orchestrator import Orchestrator
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.tools.registry import PermissionPolicy, ToolRegistry


@dataclass(slots=True)
class RuntimeContext:
    config: ConfigManager
    event_bus: EventBus
    memory: MemoryManager
    models: ModelRegistry
    tools: ToolRegistry
    orchestrator: Orchestrator
    hooks: ApiHooks
    logger: JsonLogger


def build_runtime(workspace_root: Path) -> RuntimeContext:
    cfg = ConfigManager(workspace_root)
    bus = EventBus()
    memory = MemoryManager(cfg, workspace_root)
    models = ModelRegistry.from_config(cfg)
    tools = ToolRegistry(PermissionPolicy.from_config(cfg, workspace_root))
    orchestrator = Orchestrator(config=cfg, event_bus=bus, memory=memory, models=models, tools=tools)
    hooks = ApiHooks()

    log_root = workspace_root / cfg.get("memory.storage_dir", ".harness")
    log_file = log_root / cfg.get("logging.file", "events.log")
    logger = JsonLogger(log_file=log_file)

    async def on_agent_spawned(payload: dict) -> None:
        logger.log("AGENT_SPAWNED", payload)
        await hooks.emit(HookPayload(event="AGENT_SPAWNED", data=payload))

    async def on_task_completed(payload: dict) -> None:
        logger.log("TASK_COMPLETED", payload)
        await hooks.emit(HookPayload(event="TASK_COMPLETED", data=payload))

    bus.subscribe("AGENT_SPAWNED", on_agent_spawned)
    bus.subscribe("TASK_COMPLETED", on_task_completed)

    return RuntimeContext(
        config=cfg,
        event_bus=bus,
        memory=memory,
        models=models,
        tools=tools,
        orchestrator=orchestrator,
        hooks=hooks,
        logger=logger,
    )
