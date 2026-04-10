from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model_backend: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str
    mode: str


class TaskSummary(BaseModel):
    task_id: str
    description: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    success: bool | None = None
    error: str | None = None


class TaskDetail(TaskSummary):
    output: dict
