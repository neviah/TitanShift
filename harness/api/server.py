from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI

from harness.api.schemas import ChatRequest, ChatResponse
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
