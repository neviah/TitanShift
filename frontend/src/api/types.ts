/* ==========================================================
   TitanShift API types — mirrors FastAPI schemas
   ========================================================== */

// ---- Generic ----

export interface PaginatedList<T> {
  items: T[]
  total: number
}

// ---- Ingestion ----

export interface IngestionStats {
  total_ingested: number
  total_deduplicated: number
  total_embeddings: number
}

export interface IngestionEvent {
  id: string
  source: string
  status: string
  created_at: string
  chunk_count?: number
}

export interface DedupeEvent {
  id: string
  hash: string
  status: string
  created_at: string
}

export interface UiIngestionOverviewResponse {
  stats: IngestionStats
  recent_ingestions: IngestionEvent[]
  recent_dedupe_events: DedupeEvent[]
}

// ---- Graphify Ingestion ----

export interface GraphifyRequest {
  text: string
  metadata?: Record<string, unknown>
}

export interface GraphifyResponse {
  ok: boolean
  nodes_added: number
  nodes_skipped: number
  edges_added: number
  edges_skipped: number
  node_ids: string[]
}

// ---- Tools ----

export interface ToolDefinition {
  name: string
  description: string
  category: string
  risk_level: string
  autonomous_allowed: boolean
}

// ---- Memory ----

export interface MemoryEntry {
  key: string
  value: string
  scope: string
  updated_at: string
}

// ---- Health / Status ----

export interface HealthRecord {
  name: string
  status: string
  updated_at: string
  details: Record<string, unknown>
}

export interface HealthResponse {
  ok: boolean
  subagents_enabled: boolean
  graph_backend: string
  semantic_backend: string
  default_model_backend: string
  model_connected?: boolean
  model_connection_reason?: string
  loaded_modules?: string[]
  health: HealthRecord[]
}

export interface AgentSummary {
  agent_id: string
  role: string
  subagents_enabled: boolean
  model_default_backend: string
  memory_layers: string[]
  assigned_skills: string[]
  allowed_tools: string[]
  spawned_from_task?: string | null
  created_at?: string | null
  active: boolean
}

// ---- Chat ----

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  prompt: string
  history?: ChatHistoryMessage[]
  model_backend?: string
  workflow_mode?: 'lightning' | 'superpowered'
  spec_approved?: boolean
  plan_approved?: boolean
  plan_tasks?: Array<Record<string, unknown>>
  create_task_template?: boolean
  task_template_name?: string
  budget?: {
    max_steps?: number
    max_tokens?: number
    max_duration_ms?: number
  }
}

/** A single server-sent event from the /chat/stream endpoint */
export interface StreamEvent {
  type: 'start' | 'step' | 'tool_result' | 'text_delta' | 'done' | 'error' | 'eof' | string
  [key: string]: unknown
}

export interface ChatResponse {
  success: boolean
  response: string
  model: string
  provider_model?: string | null
  mode: string
  workflow_mode?: string | null
  missing_approvals?: string[] | null
  required_skill_chain?: string[] | null
  status?: string | null
  plan_draft?: Record<string, unknown> | null
  error: string | null
  estimated_total_tokens: number | null
  task_template_id?: string | null
  task_id?: string | null
}

export interface RoleTemplate {
  role_key: string
  role_name: string
  goal: string
  required_skills: string[]
}

export interface TaskSummary {
  task_id: string
  description: string
  status: string
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  success?: boolean | null
  error?: string | null
}

export interface TaskDetail extends TaskSummary {
  output: Record<string, unknown>
}

export interface ContextProvenanceItem {
  path: string
  lines_read: number
  purpose: string
}

export interface RunArtifact {
  artifact_id: string
  kind: string
  path: string
  mime_type: string
  title: string
  summary: string
  generator: string
  backend: string
  verified?: boolean
  provenance: Record<string, unknown>
  preview: {
    url?: string
    safe_inline?: boolean
  } | null
}

export interface TaskTemplate {
  template_id: string
  name: string
  prompt: string
  workflow_mode: 'lightning' | 'superpowered' | string
  model_backend: string
  required_tools: string[]
  budget: {
    max_steps?: number
    max_tokens?: number
    max_duration_ms?: number
    [key: string]: unknown
  }
  created_at: string
  updated_at: string
  last_run_task_id?: string | null
}

export interface SchedulerJob {
  job_id: string
  description: string
  schedule_type: 'interval' | 'cron' | string
  interval_seconds: number
  cron?: string | null
  enabled: boolean
  timeout_s?: number | null
  max_failures: number
  run_count: number
  failure_count: number
  last_run_at?: string | null
  last_error?: string | null
  is_running?: boolean
  next_run_at?: string | null
}

export interface SchedulerTemplateJob {
  job_id: string
  template_id: string
  description: string
  schedule_type: 'interval' | 'cron' | string
  interval_seconds: number
  cron?: string | null
  enabled: boolean
  timeout_s?: number | null
  max_failures: number
}

export interface SchedulerTaskStackJob {
  job_id: string
  description: string
  schedule_type: 'interval' | 'cron' | string
  interval_seconds: number
  cron?: string | null
  enabled: boolean
  timeout_s?: number | null
  max_failures: number
  model_backend?: string | null
  workflow_mode?: string | null
  budget?: {
    max_steps?: number
    max_tokens?: number
    max_duration_ms?: number
    [key: string]: unknown
  }
  steps: Array<{
    source_task_id: string
    description: string
  }>
}

// ---- Artifacts ----

export interface ArtifactFile {
  artifact_type: 'spec' | 'plan'
  filename: string
  path: string
  size: number
  modified_at: string
  approved: boolean
}

export interface ArtifactApproveResponse {
  artifact_type: string
  approved: boolean
  stored_at: string
}

// ---- Workflow Metrics ----

export interface WorkflowModeStats {
  total_tasks: number
  successful_tasks?: number
  failed_tasks?: number
  success_rate?: number | null
  avg_duration_ms: number
  p50_duration_ms?: number | null
  p95_duration_ms?: number | null
}

export interface WorkflowMetrics {
  lightning: WorkflowModeStats
  superpowered: WorkflowModeStats & {
    gate_blocked_count: number
    review_ran_count: number
    review_pass_rate: number | null
    avg_review_iterations: number | null
  }
  total_tasks: number
  total_successful_tasks?: number
  total_failed_tasks?: number
  overall_success_rate?: number | null
}

export interface TaskSearchResult {
  task_id: string
  description: string
  status: string
  success: boolean | null
  snippet: string
  workflow_mode: string | null
}

export interface TaskSearchResponse {
  query: string
  total: number
  results: TaskSearchResult[]
}

export interface WorkspaceTreeNode {
  name: string
  path: string
  is_dir: boolean
  children?: WorkspaceTreeNode[]
}

export interface WorkspaceFileResponse {
  path: string
  content: string
}

// ---- Key Store Management ----

export interface ApiKeyRecord {
  id: string
  description: string
  scope: 'read' | 'admin'
  key_prefix: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  is_active: boolean
}

export interface CreateApiKeyRequest {
  description: string
  scope: 'read' | 'admin'
  expires_at?: string | null
}

export interface CreateApiKeyResponse {
  ok: boolean
  key_id: string
  raw_key: string
  record: ApiKeyRecord
}

export interface ApiKeyListResponse {
  keys: ApiKeyRecord[]
}

export interface ApiKeyEventRecord {
  id: number
  key_id: string
  event_type: string
  occurred_at: string
  metadata: Record<string, unknown>
}

export interface ApiKeyEventsResponse {
  key_id: string
  events: ApiKeyEventRecord[]
}

export interface RevokeApiKeyResponse {
  ok: boolean
  key_id: string
}

export interface LogEntry {
  timestamp: string
  event_type: string
  payload: Record<string, unknown>
}

export interface LogQueryResponse {
  items: LogEntry[]
  limit: number
  offset: number
  has_more: boolean
  next_offset?: number | null
}

export interface ToolSummary {
  name: string
  description: string
  needs_network: boolean
  required_paths: string[]
  required_commands: string[]
  allowed_by_policy: boolean
  policy_reason: string
}

export interface MemorySummary {
  working_agents: number
  working_entries: number
  short_term_agents: number
  short_term_entries: number
  long_term_scopes: number
  long_term_entries: number
}

export interface TaskCancelResponse {
  task_id: string
  cancelled: boolean
  was_running: boolean
}

export interface TaskRollbackResponse {
  task_id: string
  ok: boolean
  restored_paths: string[]
  error?: string | null
}

export interface ApiKeyStatusResponse {
  read_key_configured: boolean
  admin_key_configured: boolean
  read_key_masked?: string | null
  admin_key_masked?: string | null
}

export interface ApiKeyRotateResponse {
  ok: boolean
  scope: string
  new_key: string
}
