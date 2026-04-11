from __future__ import annotations

from datetime import datetime
from typing import Any

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


class LogQueryResponse(BaseModel):
    items: list[LogEntry]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class IncidentReport(BaseModel):
    generated_at: datetime
    signing_version: str
    report_hash: str
    scope: str
    execution_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    linked_agent_ids: list[str] = Field(default_factory=list)
    task: TaskDetail | None = None
    agent: AgentSummary | None = None
    executions: list[LogEntry] = Field(default_factory=list)
    module_errors: list[LogEntry] = Field(default_factory=list)
    diagnoses: list[EmergencyDiagnosisEntry] = Field(default_factory=list)
    related_events: list[LogEntry] = Field(default_factory=list)


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
    timeout_s: float | None = None
    max_failures: int
    run_count: int
    failure_count: int
    last_run_at: str | None = None
    last_error: str | None = None


class SchedulerHeartbeatResponse(BaseModel):
    heartbeat_count: int
    last_heartbeat_at: str | None = None
    job_count: int


class SchedulerTickResponse(BaseModel):
    ran_jobs: list[str]
    failed_jobs: list[str]
    timed_out_jobs: list[str]
    auto_disabled_jobs: list[str]
    job_count: int


class SchedulerJobToggleRequest(BaseModel):
    enabled: bool


class SchedulerJobToggleResponse(BaseModel):
    job_id: str
    enabled: bool


class AgentSummary(BaseModel):
    agent_id: str
    role: str
    subagents_enabled: bool
    model_default_backend: str
    memory_layers: list[str]
    assigned_skills: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    spawned_from_task: str | None = None
    created_at: str | None = None
    active: bool = True


class AgentSpawnRequest(BaseModel):
    description: str = Field(min_length=1)
    role: str | None = None
    model_backend: str | None = None


class AgentSpawnResponse(BaseModel):
    ok: bool
    agent_id: str
    assigned_skills: list[str]
    allowed_tools: list[str]


class AgentAssignSkillsRequest(BaseModel):
    skill_ids: list[str] = Field(min_length=1)


class AgentAssignSkillsResponse(BaseModel):
    ok: bool
    agent_id: str
    assigned_skills: list[str]
    allowed_tools: list[str]


class SkillSummary(BaseModel):
    skill_id: str
    description: str
    mode: str
    domain: str
    version: str
    tags: list[str]
    required_tools: list[str]
    ranking_score: float | None = None


class SkillExecuteRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


class SkillExecuteResponse(BaseModel):
    ok: bool
    skill_id: str
    result: dict[str, Any]


class AgentSkillExecuteRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


class AgentSkillExecuteResponse(BaseModel):
    ok: bool
    execution_id: str
    agent_id: str
    skill_id: str
    result: dict[str, Any]


class ToolSummary(BaseModel):
    name: str
    description: str
    needs_network: bool
    required_paths: list[str]
    required_commands: list[str]
    allowed_by_policy: bool
    policy_reason: str


class MemorySummary(BaseModel):
    working_agents: int
    working_entries: int
    short_term_agents: int
    short_term_entries: int
    long_term_scopes: int
    long_term_entries: int


class MemorySemanticHit(BaseModel):
    doc_id: str
    content: str
    metadata: dict


class MemoryGraphNeighbors(BaseModel):
    node_id: str
    neighbors: list[str]


class MemoryGraphNodeHit(BaseModel):
    node_id: str
    node_type: str
    properties: dict[str, str]


class EmergencyDiagnosis(BaseModel):
    hypothesis: str
    confidence: float
    suggested_fix: str


class EmergencyDiagnosisEntry(BaseModel):
    timestamp: str
    source: str
    agent_id: str | None = None
    skill_id: str | None = None
    diagnoses: list[EmergencyDiagnosis]


class EmergencyDiagnosisQueryResponse(BaseModel):
    items: list[EmergencyDiagnosisEntry]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class EmergencyDiagnosisSnapshot(BaseModel):
    generated_at: datetime
    signing_version: str
    report_hash: str
    source: str | None = None
    agent_id: str | None = None
    skill_id: str | None = None
    after: str | None = None
    before: str | None = None
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None
    items: list[EmergencyDiagnosisEntry]


class RunHistoryReport(BaseModel):
    generated_at: datetime
    signing_version: str
    report_hash: str
    redaction_applied: bool
    total_tasks: int
    failed_tasks: int
    recent_tasks: list[TaskSummary]
    recent_events: list[LogEntry]
    recent_diagnoses: list[EmergencyDiagnosisEntry]
    health: list[dict[str, Any]]
    loaded_modules: list[str]
    config_snapshot: dict[str, Any]


class RunHistoryPolicy(BaseModel):
    redact_by_default: bool
    redacted_keys: list[str]
    max_export_bytes: int


class RunHistoryExportRequest(BaseModel):
    path: str = Field(min_length=1)
    task_limit: int = Field(default=10, ge=1, le=100)
    log_limit: int = Field(default=50, ge=1, le=500)
    redact: bool | None = None


class RunHistoryExportResponse(BaseModel):
    ok: bool
    path: str
    bytes_written: int
    report_hash: str


class RunHistoryVerifyRequest(BaseModel):
    path: str = Field(min_length=1)


class RunHistoryVerifyResponse(BaseModel):
    ok: bool
    path: str
    valid: bool
    stored_hash: str
    computed_hash: str
    signing_version: str | None = None


class IncidentReportExportRequest(BaseModel):
    path: str = Field(min_length=1)
    task_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None
    after: str | None = None
    before: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class IncidentReportExportResponse(BaseModel):
    ok: bool
    path: str
    bytes_written: int
    report_hash: str


class IncidentReportVerifyRequest(BaseModel):
    path: str = Field(min_length=1)


class IncidentReportVerifyResponse(BaseModel):
    ok: bool
    path: str
    valid: bool
    stored_hash: str
    computed_hash: str
    signing_version: str | None = None


class EmergencyDiagnosisExportRequest(BaseModel):
    path: str = Field(min_length=1)
    source: str | None = None
    agent_id: str | None = None
    skill_id: str | None = None
    after: str | None = None
    before: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class EmergencyDiagnosisExportResponse(BaseModel):
    ok: bool
    path: str
    bytes_written: int
    report_hash: str


class EmergencyDiagnosisVerifyRequest(BaseModel):
    path: str = Field(min_length=1)


class EmergencyDiagnosisVerifyResponse(BaseModel):
    ok: bool
    path: str
    valid: bool
    stored_hash: str
    computed_hash: str
    signing_version: str | None = None


class ArtifactCleanupRequest(BaseModel):
    max_age_days: int | None = Field(default=None, ge=1)
    include_logs: bool = False
    dry_run: bool = False


class ArtifactCleanupResponse(BaseModel):
    ok: bool
    dry_run: bool
    max_age_days: int
    deleted_paths: list[str]
    skipped_paths: list[str]
