from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from harness.api.hooks import ApiHooks, HookPayload
from harness.emergency.module import EmergencyModule
from harness.execution.policy import ExecutionPolicy
from harness.execution.runner import ExecutionModule
from harness.logging.logger import JsonLogger
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.orchestrator import Orchestrator
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.health import HealthRegistry
from harness.runtime.module_loader import ModuleLoader
from harness.scheduler.module import ScheduledJob, Scheduler
from harness.skills.registry import SkillDefinition, SkillRegistry
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
    emergency: EmergencyModule
    health: HealthRegistry
    scheduler: Scheduler
    skills: SkillRegistry


def build_runtime(workspace_root: Path) -> RuntimeContext:
    cfg = ConfigManager(workspace_root)
    bus = EventBus()

    log_root = workspace_root / cfg.get("memory.storage_dir", ".harness")
    log_file = log_root / cfg.get("logging.file", "events.log")
    logger = JsonLogger(log_file=log_file)
    health = HealthRegistry()

    health.set("config", "healthy")
    health.set("event_bus", "healthy")
    health.set("logger", "healthy", {"file": str(log_file)})

    memory = MemoryManager(cfg, workspace_root)
    health.set("memory", "healthy")

    models = ModelRegistry.from_config(cfg)
    health.set("models", "healthy", {"default": cfg.get("model.default_backend")})

    def on_tool_audit(payload: dict) -> None:
        logger.log("TOOL_AUDIT", payload)

    tools = ToolRegistry(
        PermissionPolicy.from_config(cfg, workspace_root),
        audit_sink=on_tool_audit,
    )
    health.set("tools", "healthy")

    execution = ExecutionModule(
        policy=ExecutionPolicy.from_config(cfg, workspace_root),
        default_cwd=workspace_root,
    )
    health.set("execution", "healthy")

    register_builtin_tools(tools, execution)

    skills = SkillRegistry()
    skills.register_skill(
        SkillDefinition(
            skill_id="reactive_chat",
            description="Single-agent reactive response generation",
            mode="prompt",
            domain="orchestration",
            tags=["chat", "reactive", "phase1"],
            required_tools=[],
            prompt_template="Respond to user input reactively and safely: {input}",
        )
    )
    skills.register_skill(
        SkillDefinition(
            skill_id="safe_shell_command",
            description="Policy-constrained shell command execution wrapper",
            mode="code",
            domain="execution",
            tags=["tools", "execution", "safety", "phase1"],
            required_tools=["shell_command"],
        )
    )

    async def _safe_shell_handler(payload: dict) -> dict:
        command = str(payload.get("command", "")).strip()
        if not command:
            return {"ok": False, "error": "Missing command"}
        args = {"command": command}
        result = await tools.execute_tool("shell_command", args)
        return {"ok": True, "tool": "shell_command", "result": result}

    skills.register_code_handler("safe_shell_command", _safe_shell_handler)
    health.set("skills", "healthy", {"count": len(skills.list_skills())})

    orchestrator = Orchestrator(config=cfg, event_bus=bus, memory=memory, models=models, skills=skills, tools=tools)
    health.set("orchestrator", "healthy")

    for tool in tools.list_tools():
        memory.graph_add_node(f"tool:{tool.name}", "tool", {"name": tool.name, "description": tool.description})

    for skill in skills.list_skills():
        memory.graph_add_node(
            f"skill:{skill.skill_id}",
            "skill",
            {
                "skill_id": skill.skill_id,
                "description": skill.description,
                "domain": skill.domain,
                "tags": ",".join(skill.tags),
            },
        )
        for tool_name in skill.required_tools:
            memory.graph_add_edge(f"skill:{skill.skill_id}", f"tool:{tool_name}", "requires_tool")
            memory.graph_add_edge(f"tool:{tool_name}", f"skill:{skill.skill_id}", "enables_skill")

    hooks = ApiHooks()
    health.set("api_hooks", "healthy")

    module_loader = ModuleLoader(modules_root=workspace_root / cfg.get("runtime.module_path", "modules"))
    workspace_import_root = str(workspace_root.resolve())
    if workspace_import_root not in sys.path:
        sys.path.insert(0, workspace_import_root)
    emergency = EmergencyModule()
    scheduler = Scheduler()
    scheduler.register_job(
        ScheduledJob(
            job_id="scheduler_heartbeat",
            description="Publish heartbeat tick and keep scheduler health updated",
            interval_seconds=60,
            callback=lambda: bus.publish("HEARTBEAT_TICK", {"source": "scheduler"}),
        )
    )
    health.set("emergency", "healthy")
    health.set("scheduler", "healthy", {"jobs": [j["job_id"] for j in scheduler.list_jobs()]})

    async def on_agent_spawned(payload: dict) -> None:
        logger.log("AGENT_SPAWNED", payload)
        await hooks.emit(HookPayload(event="AGENT_SPAWNED", data=payload))

    async def on_task_completed(payload: dict) -> None:
        logger.log("TASK_COMPLETED", payload)
        await hooks.emit(HookPayload(event="TASK_COMPLETED", data=payload))

    async def on_module_error(payload: dict) -> None:
        logger.log("MODULE_ERROR", payload)
        health.set(
            str(payload.get("source", "unknown")),
            "degraded",
            {"last_error": str(payload.get("error", "unknown"))},
        )
        diagnoses = await emergency.on_failure(payload)
        logger.log(
            "EMERGENCY_DIAGNOSIS",
            {
                "source": payload.get("source", "unknown"),
                "diagnoses": [d.__dict__ for d in diagnoses],
            },
        )
        await hooks.emit(HookPayload(event="MODULE_ERROR", data=payload))

    async def on_heartbeat_tick(payload: dict) -> None:
        logger.log("HEARTBEAT_TICK", payload)
        health.set("scheduler", "healthy", {"last_heartbeat_source": payload.get("source", "unknown")})
        await hooks.emit(HookPayload(event="HEARTBEAT_TICK", data=payload))

    bus.subscribe("AGENT_SPAWNED", on_agent_spawned)
    bus.subscribe("TASK_COMPLETED", on_task_completed)
    bus.subscribe("MODULE_ERROR", on_module_error)
    bus.subscribe("HEARTBEAT_TICK", on_heartbeat_tick)

    for mod_name in module_loader.discover_modules():
        module_loader.load_from_package(f"modules.{mod_name}")
    logger.log("MODULES_LOADED", {"modules": module_loader.list_modules()})
    health.set("module_loader", "healthy", {"modules": module_loader.list_modules()})

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
        emergency=emergency,
        health=health,
        scheduler=scheduler,
        skills=skills,
    )
