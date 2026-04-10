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


class LogEntry(BaseModel):
    timestamp: str
    event_type: str
    payload: dict


class ConfigUpdateRequest(BaseModel):
    key: str = Field(min_length=1)
    value: object


class ConfigUpdateResponse(BaseModel):
    ok: bool
    key: str
    value: object


class SchedulerJob(BaseModel):
    job_id: str
    description: str
    interval_seconds: int
    enabled: bool
    run_count: int
    last_run_at: str | None = None


class SchedulerHeartbeatResponse(BaseModel):
    heartbeat_count: int
    last_heartbeat_at: str | None = None
    job_count: int


class SchedulerTickResponse(BaseModel):
    ran_jobs: list[str]
    job_count: int


class AgentSummary(BaseModel):
    agent_id: str
    role: str
    subagents_enabled: bool
    model_default_backend: str
    memory_layers: list[str]


class SkillSummary(BaseModel):
    skill_id: str
    description: str
    tags: list[str]
    required_tools: list[str]


class ToolSummary(BaseModel):
    name: str
    description: str
    needs_network: bool
    required_paths: list[str]
    required_commands: list[str]
    allowed_by_policy: bool
    policy_reason: str
