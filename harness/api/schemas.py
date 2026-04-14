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
    workflow_mode: str | None = None
    spec_approved: bool | None = None
    plan_approved: bool | None = None
    plan_tasks: list[dict[str, Any]] | None = None
    create_task_template: bool = False
    task_template_name: str | None = None


class ChatResponse(BaseModel):
    success: bool
    response: str
    model: str
    mode: str
    workflow_mode: str | None = None
    missing_approvals: list[str] | None = None
    required_skill_chain: list[str] | None = None
    error: str | None = None
    estimated_total_tokens: int | None = None
    task_template_id: str | None = None


class TaskTemplate(BaseModel):
    template_id: str
    name: str
    prompt: str
    workflow_mode: str
    model_backend: str
    required_tools: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    last_run_task_id: str | None = None


class TaskTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    workflow_mode: str | None = None
    model_backend: str | None = None
    required_tools: list[str] | None = None
    budget: BudgetOverride | None = None


class TaskTemplateCreateResponse(BaseModel):
    ok: bool
    template: TaskTemplate


class TaskTemplateRunRequest(BaseModel):
    model_backend: str | None = None
    workflow_mode: str | None = None
    budget: BudgetOverride | None = None


class TaskTemplateRunResponse(BaseModel):
    ok: bool
    template_id: str
    task_id: str
    status: str


class SchedulerTemplateJobCreateRequest(BaseModel):
    template_id: str = Field(min_length=1)
    job_id: str | None = None
    description: str | None = None
    schedule_type: str = "interval"
    interval_seconds: int = Field(default=60, ge=1)
    cron: str | None = None
    enabled: bool = True
    timeout_s: float | None = None
    max_failures: int = Field(default=3, ge=1)


class SchedulerTemplateJobCreateResponse(BaseModel):
    ok: bool
    job_id: str
    template_id: str


class SchedulerTemplateJob(BaseModel):
    job_id: str
    template_id: str
    description: str
    schedule_type: str
    interval_seconds: int
    cron: str | None = None
    enabled: bool
    timeout_s: float | None = None
    max_failures: int


class SchedulerTaskStackStep(BaseModel):
    source_task_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SchedulerTaskStackJobCreateRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1)
    job_id: str | None = None
    description: str | None = None
    schedule_type: str = "interval"
    interval_seconds: int = Field(default=60, ge=1)
    cron: str | None = None
    enabled: bool = True
    timeout_s: float | None = None
    max_failures: int = Field(default=3, ge=1)
    model_backend: str | None = None
    workflow_mode: str | None = None
    budget: BudgetOverride | None = None


class SchedulerTaskStackJobCreateResponse(BaseModel):
    ok: bool
    job_id: str
    task_count: int


class SchedulerTaskStackJob(BaseModel):
    job_id: str
    description: str
    schedule_type: str
    interval_seconds: int
    cron: str | None = None
    enabled: bool
    timeout_s: float | None = None
    max_failures: int
    model_backend: str | None = None
    workflow_mode: str | None = None
    budget: dict[str, object] = Field(default_factory=dict)
    steps: list[SchedulerTaskStackStep] = Field(default_factory=list)


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


class WorkspaceTreeNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    children: list["WorkspaceTreeNode"] = Field(default_factory=list)


class WorkspaceFileResponse(BaseModel):
    path: str
    content: str


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


class IncidentCorrelation(BaseModel):
    failure_ids: list[str] = Field(default_factory=list)
    fix_execution_count: int = 0
    correlation_sources: list[str] = Field(default_factory=list)
    resolved_execution_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    fix_executions: list[LogEntry] = Field(default_factory=list)
    correlation: IncidentCorrelation = Field(default_factory=IncidentCorrelation)
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
    schedule_type: str = "interval"
    interval_seconds: int
    cron: str | None = None
    enabled: bool
    timeout_s: float | None = None
    max_failures: int
    run_count: int
    failure_count: int
    last_run_at: str | None = None
    last_error: str | None = None
    is_running: bool = False
    next_run_at: str | None = None


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
    missed_heartbeat: bool = False
    newly_missed_heartbeat: bool = False
    recovered_heartbeat: bool = False
    heartbeat_lag_s: float | None = None
    heartbeat_timeout_s: float | None = None


class SchedulerMaintenanceRegisterResponse(BaseModel):
    ok: bool
    registered_jobs: list[str]


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


class SkillMarketItem(BaseModel):
    skill_id: str
    name: str
    description: str
    mode: str
    domain: str
    version: str
    tags: list[str]
    required_tools: list[str]
    dependencies: list[str]
    installed: bool
    installable: bool
    missing_dependencies: list[str]
    missing_tools: list[str]


class SkillMarketInstallRequest(BaseModel):
    skill_id: str = Field(min_length=1)


class SkillMarketInstallResponse(BaseModel):
    ok: bool
    skill_id: str
    installed: bool
    version: str


class SkillMarketUninstallRequest(BaseModel):
    skill_id: str = Field(min_length=1)


class SkillMarketUninstallResponse(BaseModel):
    ok: bool
    skill_id: str
    uninstalled: bool
    removed_tool_ids: list[str] = Field(default_factory=list)
    removed_manifest: bool = False


class SkillMarketUpdateRequest(BaseModel):
    skill_id: str = Field(min_length=1)


class SkillMarketUpdateResponse(BaseModel):
    ok: bool
    skill_id: str
    updated: bool
    version: str


class SkillMarketRemoteSyncRequest(BaseModel):
    source: str = Field(min_length=1)
    force: bool = False


class SkillMarketRemoteSyncResponse(BaseModel):
    ok: bool
    source: str
    pulled_count: int
    index_hash: str
    synced_at: str


class SkillMarketRemoteStatusResponse(BaseModel):
    synced: bool
    source: str | None = None
    synced_at: str | None = None
    pulled_count: int = 0
    index_hash: str | None = None


class SkillRepoIntakeRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    auto_install: bool = True
    trust_policy: str = "github_only"


class SkillRepoIntakeResponse(BaseModel):
    ok: bool
    repo_url: str
    repo_name: str
    classification: str
    recommended_artifact: str
    confidence: float
    trust_policy: str = "github_only"
    trust_passed: bool = False
    trust_reason: str | None = None
    installed_skill_id: str | None = None
    generated_tool_ids: list[str] = Field(default_factory=list)
    generated_adapters: list[dict[str, Any]] = Field(default_factory=list)
    intake_manifest: dict[str, Any] = Field(default_factory=dict)
    process_log: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class UiMarketOverviewResponse(BaseModel):
    total_listed: int
    installed_count: int
    installable_count: int
    non_installable_count: int
    remote_status: SkillMarketRemoteStatusResponse
    recent_events: list[LogEntry] = Field(default_factory=list)


class UiIngestionOverviewResponse(BaseModel):
    stats: IngestionStatsResponse
    recent_ingestions: list[LogEntry] = Field(default_factory=list)
    recent_dedupe_events: list[IngestionDedupeEntry] = Field(default_factory=list)


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


class MemoryGraphMigrationExportRequest(BaseModel):
    path: str = Field(min_length=1)
    backend: str = Field(default="local")
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None


class MemoryGraphMigrationImportRequest(BaseModel):
    path: str = Field(min_length=1)
    backend: str = Field(default="local")
    clear_existing: bool = False
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None


class MemoryGraphMigrationResponse(BaseModel):
    ok: bool
    backend: str
    path: str
    nodes: int
    edges: int
    details: dict[str, Any] = Field(default_factory=dict)


class EmergencyDiagnosis(BaseModel):
    hypothesis: str
    confidence: float
    suggested_fix: str


class EmergencyFixAction(BaseModel):
    action_type: str
    target_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class EmergencyFixPlan(BaseModel):
    failure_id: str
    recommended_hypothesis: str
    risk_level: str
    requires_user_approval: bool = True
    actions: list[EmergencyFixAction] = Field(default_factory=list)
    notes: str


class EmergencyConsensusEntry(BaseModel):
    hypothesis: str
    confidence_avg: float
    source_weight: float
    vote_count: int
    consensus_score: float


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


class EmergencyAnalyzeRequest(BaseModel):
    source: str = Field(min_length=1)
    error: str = Field(min_length=1)
    agent_id: str | None = None
    skill_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class EmergencyAnalyzeResponse(BaseModel):
    ok: bool
    failure_id: str
    diagnoses: list[EmergencyDiagnosis]
    selected_hypothesis: str
    consensus: list[EmergencyConsensusEntry]
    fix_plan: EmergencyFixPlan


class EmergencyFixApplyRequest(BaseModel):
    fix_plan: EmergencyFixPlan
    approved: bool = False
    dry_run: bool = True


class EmergencyFixApplyResponse(BaseModel):
    ok: bool
    applied: bool
    dry_run: bool
    execution_id: str | None = None
    rollback_available: bool = False
    results: list[dict[str, Any]]
    message: str


class EmergencyFixRollbackRequest(BaseModel):
    execution_id: str = Field(min_length=1)
    dry_run: bool = True


class EmergencyFixRollbackResponse(BaseModel):
    ok: bool
    rolled_back: bool
    dry_run: bool
    execution_id: str
    results: list[dict[str, Any]]
    message: str


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
    include_fix_executions: bool = True
    fix_event_type: str | None = None
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


class EmergencyFixExecutionQueryResponse(BaseModel):
    items: list[LogEntry]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class EmergencyFixExecutionSnapshot(BaseModel):
    generated_at: datetime
    signing_version: str
    report_hash: str
    execution_id: str | None = None
    failure_id: str | None = None
    after: str | None = None
    before: str | None = None
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None
    items: list[LogEntry]


class EmergencyFixExecutionExportRequest(BaseModel):
    path: str = Field(min_length=1)
    execution_id: str | None = None
    failure_id: str | None = None
    after: str | None = None
    before: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class EmergencyFixExecutionExportResponse(BaseModel):
    ok: bool
    path: str
    bytes_written: int
    report_hash: str


class EmergencyFixExecutionVerifyRequest(BaseModel):
    path: str = Field(min_length=1)


class EmergencyFixExecutionVerifyResponse(BaseModel):
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


class ArtifactFile(BaseModel):
    artifact_type: str
    filename: str
    path: str
    size: int
    modified_at: str
    approved: bool = False


class ArtifactApproveRequest(BaseModel):
    artifact_type: str


class ArtifactApproveResponse(BaseModel):
    artifact_type: str
    approved: bool
    stored_at: str


class WorkflowModeStats(BaseModel):
    total_tasks: int
    avg_duration_ms: float


class SuperpoweredModeStats(WorkflowModeStats):
    gate_blocked_count: int
    review_ran_count: int
    review_pass_rate: float | None = None
    avg_review_iterations: float | None = None


class WorkflowMetrics(BaseModel):
    lightning: WorkflowModeStats
    superpowered: SuperpoweredModeStats
    total_tasks: int



class ArtifactCleanupResponse(BaseModel):
    ok: bool
    dry_run: bool
    max_age_days: int
    deleted_paths: list[str]
    skipped_paths: list[str]


class GraphifyRequest(BaseModel):
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphifyResponse(BaseModel):
    ok: bool
    nodes_added: int
    nodes_skipped: int
    edges_added: int
    edges_skipped: int
    node_ids: list[str]


class IngestionStatsResponse(BaseModel):
    total_ingestions: int
    total_nodes_added: int
    total_nodes_skipped: int
    total_edges_added: int
    total_edges_skipped: int
    last_ingested_at: str | None = None


class IngestionDedupeEntry(BaseModel):
    timestamp: str
    node_id: str
    reason: str
    confidence: float
    threshold: float


class IngestionDedupeLogResponse(BaseModel):
    items: list[IngestionDedupeEntry]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None
