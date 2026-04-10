from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetOverride(BaseModel):
    max_steps: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_duration_ms: int | None = Field(default=None, ge=1)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model_backend: str | None = None
    budget: BudgetOverride | None = None


class ChatResponse(BaseModel):
    success: bool
    response: str
    model: str
    mode: str
    error: str | None = None
    estimated_total_tokens: int | None = None


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
