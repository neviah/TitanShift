from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException

from harness.api.schemas import (
    AgentSummary,
    ChatRequest,
    ChatResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    LogEntry,
    SchedulerHeartbeatResponse,
    SchedulerJob,
    SchedulerTickResponse,
    TaskDetail,
    TaskSummary,
)
from harness.runtime.bootstrap import RuntimeContext, build_runtime
from harness.runtime.types import Task


def create_app(workspace_root: Path) -> FastAPI:
    runtime: RuntimeContext = build_runtime(workspace_root)
    app = FastAPI(title="TitantShift Harness API", version="0.1.0")

    @app.get("/status")
    async def status() -> dict:
        return {
            "ok": True,
            "subagents_enabled": runtime.config.get("orchestrator.enable_subagents"),
            "graph_backend": runtime.config.get("memory.graph_backend"),
            "semantic_backend": runtime.config.get("memory.semantic_backend"),
            "default_model_backend": runtime.config.get("model.default_backend"),
            "health": runtime.health.as_list(),
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest) -> ChatResponse:
        task_input: dict = {}
        if body.model_backend:
            task_input["model_backend"] = body.model_backend
        if body.budget:
            task_input["budget"] = body.budget.model_dump(exclude_none=True)

        task = Task(
            id=str(uuid.uuid4()),
            description=body.prompt,
            input=task_input,
        )
        result = await runtime.orchestrator.run_reactive_task(task)
        return ChatResponse(
            success=result.success,
            response=result.output.get("response", ""),
            model=result.output.get("model", "unknown"),
            mode=result.output.get("mode", "reactive"),
            error=result.error,
            estimated_total_tokens=result.output.get("estimated_total_tokens"),
        )

    @app.get("/tasks", response_model=list[TaskSummary])
    async def list_tasks() -> list[TaskSummary]:
        return [TaskSummary(**t) for t in runtime.orchestrator.list_tasks()]

    @app.get("/tasks/{task_id}", response_model=TaskDetail)
    async def get_task(task_id: str) -> TaskDetail:
        task = runtime.orchestrator.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskDetail(**task)

    @app.get("/logs", response_model=list[LogEntry])
    async def get_logs(
        event_type: str | None = None,
        task_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[LogEntry]:
        clamped_limit = max(1, min(limit, 1000))
        rows = runtime.logger.query(
            event_type=event_type,
            task_id=task_id,
            source=source,
            limit=clamped_limit,
        )
        return [LogEntry(**r) for r in rows]

    @app.get("/config")
    async def get_config() -> dict:
        return {
            "model.default_backend": runtime.config.get("model.default_backend"),
            "orchestrator.enable_subagents": runtime.config.get("orchestrator.enable_subagents"),
            "state_machine.default_budget.max_steps": runtime.config.get("state_machine.default_budget.max_steps"),
            "state_machine.default_budget.max_tokens": runtime.config.get("state_machine.default_budget.max_tokens"),
            "state_machine.default_budget.max_duration_ms": runtime.config.get(
                "state_machine.default_budget.max_duration_ms"
            ),
            "tools.deny_all_by_default": runtime.config.get("tools.deny_all_by_default"),
            "tools.allow_network": runtime.config.get("tools.allow_network"),
        }

    @app.post("/config", response_model=ConfigUpdateResponse)
    async def update_config(body: ConfigUpdateRequest) -> ConfigUpdateResponse:
        runtime.config.set(body.key, body.value)
        runtime.logger.log("CONFIG_UPDATED", {"key": body.key})
        return ConfigUpdateResponse(ok=True, key=body.key, value=runtime.config.get(body.key))

    @app.get("/scheduler/jobs", response_model=list[SchedulerJob])
    async def scheduler_jobs() -> list[SchedulerJob]:
        return [SchedulerJob(**j) for j in runtime.scheduler.list_jobs()]

    @app.get("/agents", response_model=list[AgentSummary])
    async def agents() -> list[AgentSummary]:
        return [
            AgentSummary(
                agent_id="main-agent",
                role=runtime.config.get("orchestrator.default_role", "General Agent"),
                subagents_enabled=runtime.config.get("orchestrator.enable_subagents", False),
                model_default_backend=runtime.config.get("model.default_backend", "local_stub"),
                memory_layers=["working", "short_term", "long_term", "semantic", "graph"],
            )
        ]

    @app.post("/scheduler/heartbeat", response_model=SchedulerHeartbeatResponse)
    async def scheduler_heartbeat() -> SchedulerHeartbeatResponse:
        runtime.logger.log("SCHEDULER_HEARTBEAT", {"source": "api"})
        hb = runtime.scheduler.heartbeat()
        return SchedulerHeartbeatResponse(**hb)

    @app.post("/scheduler/tick", response_model=SchedulerTickResponse)
    async def scheduler_tick() -> SchedulerTickResponse:
        result = await runtime.scheduler.tick()
        runtime.logger.log("SCHEDULER_TICK", result)
        return SchedulerTickResponse(**result)

    return app
