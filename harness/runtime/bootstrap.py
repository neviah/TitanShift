from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.api.hooks import ApiHooks, HookPayload
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionModule
from harness.logging.logger import JsonLogger
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.orchestrator import Orchestrator
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.module_loader import ModuleLoader
from harness.tools.builtin import register_builtin_tools
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
    module_loader: ModuleLoader
    execution: ExecutionModule


def build_runtime(workspace_root: Path) -> RuntimeContext:
    cfg = ConfigManager(workspace_root)
    bus = EventBus()

    log_root = workspace_root / cfg.get("memory.storage_dir", ".harness")
    log_file = log_root / cfg.get("logging.file", "events.log")
    logger = JsonLogger(log_file=log_file)

    memory = MemoryManager(cfg, workspace_root)
    models = ModelRegistry.from_config(cfg)

    def on_tool_audit(payload: dict) -> None:
        logger.log("TOOL_AUDIT", payload)

    tools = ToolRegistry(
        PermissionPolicy.from_config(cfg, workspace_root),
        audit_sink=on_tool_audit,
    )
    execution = ExecutionModule(
        policy=ExecutionPolicy.from_config(cfg, workspace_root),
        default_cwd=workspace_root,
    )
    register_builtin_tools(tools, execution)

    orchestrator = Orchestrator(config=cfg, event_bus=bus, memory=memory, models=models, tools=tools)
    hooks = ApiHooks()
    module_loader = ModuleLoader(modules_root=workspace_root / cfg.get("runtime.module_path", "modules"))

    async def on_agent_spawned(payload: dict) -> None:
        logger.log("AGENT_SPAWNED", payload)
        await hooks.emit(HookPayload(event="AGENT_SPAWNED", data=payload))

    async def on_task_completed(payload: dict) -> None:
        logger.log("TASK_COMPLETED", payload)
        await hooks.emit(HookPayload(event="TASK_COMPLETED", data=payload))

    bus.subscribe("AGENT_SPAWNED", on_agent_spawned)
    bus.subscribe("TASK_COMPLETED", on_task_completed)

    for mod_name in module_loader.discover_modules():
        module_loader.load_from_package(f"modules.{mod_name}")
    logger.log("MODULES_LOADED", {"modules": module_loader.list_modules()})

    return RuntimeContext(
        config=cfg,
        event_bus=bus,
        memory=memory,
        models=models,
        tools=tools,
        orchestrator=orchestrator,
        hooks=hooks,
        logger=logger,
        module_loader=module_loader,
        execution=execution,
    )
