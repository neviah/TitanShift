import type {
  UiIngestionOverviewResponse,
  HealthResponse,
  ChatRequest,
  ChatResponse,
  TaskSummary,
  TaskDetail,
  TaskTemplate,
  SchedulerJob,
  SchedulerTaskStackJob,
  SchedulerTemplateJob,
  WorkspaceTreeNode,
  WorkspaceFileResponse,
  ToolSummary,
  MemorySummary,
  AgentSummary,
  LogQueryResponse,
  GraphifyRequest,
  GraphifyResponse,
  RoleTemplate,
  ArtifactFile,
  ArtifactApproveResponse,
  WorkflowMetrics,
  TaskSearchResponse,
  TaskCancelResponse,
  TaskRollbackResponse,
  ApiKeyStatusResponse,
  ApiKeyRotateResponse,
  CreateApiKeyRequest,
  CreateApiKeyResponse,
  ApiKeyListResponse,
  ApiKeyEventsResponse,
  RevokeApiKeyResponse,
} from './types'

export const API_BASE = '/api'
export type TaskScope = 'workspace' | 'all'

type AuthScope = 'read' | 'admin'

const LOCAL_READ_KEY = 'titanshift-api-key'
const LOCAL_ADMIN_KEY = 'titanshift-admin-api-key'

export class ApiClientError extends Error {
  status: number | null
  statusText: string | null
  path: string
  authScope: AuthScope
  responseBody: string

  constructor(args: {
    message: string
    path: string
    authScope: AuthScope
    status?: number | null
    statusText?: string | null
    responseBody?: string
  }) {
    super(args.message)
    this.name = 'ApiClientError'
    this.status = args.status ?? null
    this.statusText = args.statusText ?? null
    this.path = args.path
    this.authScope = args.authScope
    this.responseBody = args.responseBody ?? ''
  }
}

function isLocalhost(): boolean {
  if (typeof window === 'undefined') return false
  return window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost'
}

export function getStoredApiKey(scope: AuthScope): string {
  if (typeof window === 'undefined') return ''
  const storageKey = scope === 'admin' ? LOCAL_ADMIN_KEY : LOCAL_READ_KEY
  const stored = window.localStorage.getItem(storageKey)?.trim() ?? ''
  if (stored) return stored

  // Local dev convenience: match the repo's current local harness defaults so the UI works
  // out of the box during localhost testing. Persisted localStorage values override this.
  if (isLocalhost()) {
    return scope === 'admin' ? 'admin123' : 'read123'
  }

  return ''
}

function parseBackendErrorMessage(rawBody: string): string {
  const body = rawBody.trim()
  if (!body) return ''
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>
    const detail = parsed.detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      if (typeof first === 'string' && first.trim()) return first.trim()
      if (first && typeof first === 'object' && 'msg' in first) {
        const msg = (first as { msg?: unknown }).msg
        if (typeof msg === 'string' && msg.trim()) return msg.trim()
      }
    }
    if (typeof parsed.error === 'string' && parsed.error.trim()) return parsed.error.trim()
    if (typeof parsed.message === 'string' && parsed.message.trim()) return parsed.message.trim()
  } catch {
    // Ignore parse errors and return raw body below.
  }
  return body
}

export function normalizeApiError(error: unknown): string {
  if (error instanceof ApiClientError) {
    const backendMessage = parseBackendErrorMessage(error.responseBody)
    if (error.status === 401) {
      return 'API authentication failed. Configure a valid local TitanShift API key. No account login is required.'
    }
    if (error.status === 403) {
      if (error.authScope === 'admin') {
        return 'This action requires an admin API key. Update the local admin key and retry.'
      }
      return 'Permission denied by the local API key policy.'
    }
    if (error.status === 404) {
      return 'Requested API route was not found. Confirm TitanShift backend version and endpoint compatibility.'
    }
    if (error.status === 0 || error.status === null) {
      return 'Cannot reach TitanShift backend. Start the local API server and verify network/connectivity settings.'
    }
    if (backendMessage) {
      return `API request failed (${error.status}): ${backendMessage}`
    }
    return `API request failed (${error.status ?? 'unknown'}${error.statusText ? ` ${error.statusText}` : ''}).`
  }

  if (error instanceof TypeError) {
    const msg = error.message.toLowerCase()
    if (msg.includes('failed to fetch') || msg.includes('networkerror') || msg.includes('load failed')) {
      return 'Cannot reach TitanShift backend. Start the local API server and verify network/connectivity settings.'
    }
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return String(error)
}

async function request<T>(path: string, init?: RequestInit, authScope: AuthScope = 'read'): Promise<T> {
  const apiKey = getStoredApiKey(authScope)
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(apiKey ? { 'x-api-key': apiKey } : {}),
        ...init?.headers,
      },
      ...init,
    })
  } catch (error) {
    throw new ApiClientError({
      message: normalizeApiError(error),
      path,
      authScope,
      status: 0,
      statusText: 'NETWORK_ERROR',
    })
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiClientError({
      message: `${res.status} ${res.statusText}`,
      path,
      authScope,
      status: res.status,
      statusText: res.statusText,
      responseBody: body,
    })
  }
  return res.json() as Promise<T>
}

// ---- UI overview ----

export function fetchIngestionOverview(): Promise<UiIngestionOverviewResponse> {
  return request('/ui/ingestion/overview')
}

// ---- Graphify Ingestion ----

export function graphifyIngest(body: GraphifyRequest): Promise<GraphifyResponse> {
  return request('/ingestion/graphify', {
    method: 'POST',
    body: JSON.stringify(body),
  }, 'admin')
}

// ---- Health / Status ----

export function fetchStatus(): Promise<HealthResponse> {
  return request('/status')
}

// ---- Config ----

export function fetchConfig(): Promise<Record<string, unknown>> {
  return request('/config')
}

export function updateConfig(key: string, value: unknown): Promise<unknown> {
  return request('/config', {
    method: 'POST',
    body: JSON.stringify({ key, value }),
  }, 'admin')
}

// ---- Chat ----

export function sendChat(requestBody: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify(requestBody),
    signal,
  })
}

export function fetchTasks(scope: TaskScope = 'workspace'): Promise<TaskSummary[]> {
  return request(`/tasks?scope=${encodeURIComponent(scope)}`)
}

export function fetchAgents(): Promise<AgentSummary[]> {
  return request('/agents')
}

export function fetchRoleTemplates(): Promise<RoleTemplate[]> {
  return request('/roles/templates')
}

export function fetchTaskDetail(taskId: string, scope: TaskScope = 'workspace'): Promise<TaskDetail> {
  return request(`/tasks/${taskId}?scope=${encodeURIComponent(scope)}`)
}

export function fetchTaskTemplates(): Promise<TaskTemplate[]> {
  return request('/tasks/templates')
}

export function fetchSchedulerJobs(): Promise<SchedulerJob[]> {
  return request('/scheduler/jobs')
}

export function fetchSchedulerTemplateJobs(): Promise<SchedulerTemplateJob[]> {
  return request('/scheduler/template-jobs')
}

export function fetchSchedulerTaskStacks(): Promise<SchedulerTaskStackJob[]> {
  return request('/scheduler/task-stacks')
}

export function createSchedulerTaskStack(body: {
  task_ids: string[]
  job_id?: string
  description?: string
  schedule_type: 'interval' | 'cron'
  interval_seconds?: number
  cron?: string
  enabled?: boolean
  timeout_s?: number
  max_failures?: number
  model_backend?: string
  workflow_mode?: 'lightning' | 'superpowered'
  budget?: {
    max_steps?: number
    max_tokens?: number
    max_duration_ms?: number
  }
}): Promise<{ ok: boolean; job_id: string; task_count: number }> {
  return request('/scheduler/task-stacks', {
    method: 'POST',
    body: JSON.stringify(body),
  }, 'admin')
}

export function deleteSchedulerTaskStack(jobId: string): Promise<{ ok: boolean; job_id: string; deleted: boolean }> {
  return request(`/scheduler/task-stacks/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
  }, 'admin')
}

export function createSchedulerTemplateJob(body: {
  template_id: string
  job_id?: string
  description?: string
  schedule_type: 'interval' | 'cron'
  interval_seconds?: number
  cron?: string
  enabled?: boolean
  timeout_s?: number
  max_failures?: number
}): Promise<{ ok: boolean; job_id: string; template_id: string }> {
  return request('/scheduler/template-jobs', {
    method: 'POST',
    body: JSON.stringify(body),
  }, 'admin')
}

export function deleteSchedulerTemplateJob(jobId: string): Promise<{ ok: boolean; job_id: string; deleted: boolean }> {
  return request(`/scheduler/template-jobs/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
  }, 'admin')
}

export function triggerSchedulerTick(): Promise<{
  ran_jobs: string[]
  failed_jobs: string[]
  timed_out_jobs: string[]
  auto_disabled_jobs: string[]
  job_count: number
}> {
  return request('/scheduler/tick', {
    method: 'POST',
  }, 'admin')
}

export function setSchedulerJobEnabled(jobId: string, enabled: boolean): Promise<{ job_id: string; enabled: boolean }> {
  return request(`/scheduler/jobs/${encodeURIComponent(jobId)}/enabled`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  }, 'admin')
}

export function fetchWorkspaceTree(): Promise<WorkspaceTreeNode[]> {
  return request('/workspace/tree')
}

export function fetchWorkspaceInfo(): Promise<{ root: string }> {
  return request('/workspace/info')
}

// ---- Task Cancellation & Rollback ----

export function cancelTask(taskId: string): Promise<TaskCancelResponse> {
  return request(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function rollbackTask(taskId: string): Promise<TaskRollbackResponse> {
  return request(`/tasks/${encodeURIComponent(taskId)}/rollback`, { method: 'POST' }, 'admin')
}

export function deleteTask(taskId: string, scope: TaskScope = 'workspace'): Promise<void> {
  return request(`/tasks/${encodeURIComponent(taskId)}?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' })
}

export function purgeTasks(scope: TaskScope = 'workspace'): Promise<{ ok: boolean; scope: TaskScope; deleted_count: number }> {
  return request(`/tasks/purge?scope=${encodeURIComponent(scope)}`, { method: 'POST' })
}

// ---- API Key Management ----

export function fetchApiKeyStatus(): Promise<ApiKeyStatusResponse> {
  return request('/api-keys/status', {}, 'admin')
}

export function rotateApiKey(scope: 'read' | 'admin'): Promise<ApiKeyRotateResponse> {
  return request(`/api-keys/rotate?scope=${scope}`, { method: 'POST' }, 'admin')
}

// ---- Key Store CRUD ----

export function listApiKeys(): Promise<ApiKeyListResponse> {
  return request('/api-keys', {}, 'admin')
}

export function createApiKey(body: CreateApiKeyRequest): Promise<CreateApiKeyResponse> {
  return request('/api-keys', { method: 'POST', body: JSON.stringify(body) }, 'admin')
}

export function revokeApiKey(keyId: string): Promise<RevokeApiKeyResponse> {
  return request(`/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' }, 'admin')
}

export function fetchApiKeyEvents(keyId: string, limit = 50): Promise<ApiKeyEventsResponse> {
  return request(`/api-keys/${encodeURIComponent(keyId)}/events?limit=${limit}`, {}, 'admin')
}

export function setWorkspaceRoot(path: string): Promise<{ root: string }> {
  return request('/workspace/set-root', {
    method: 'POST',
    body: JSON.stringify({ path }),
  })
}

export function fetchWorkspaceFile(path: string): Promise<WorkspaceFileResponse> {
  return request(`/workspace/file?path=${encodeURIComponent(path)}`)
}

export function fetchTools(): Promise<ToolSummary[]> {
  return request('/tools')
}

export function fetchMemorySummary(): Promise<MemorySummary> {
  return request('/memory/summary')
}

export function fetchLogs(limit = 20): Promise<LogQueryResponse> {
  return request(`/logs?limit=${limit}`)
}

// ---- Artifacts ----

export function fetchArtifacts(): Promise<ArtifactFile[]> {
  return request('/artifacts')
}

export function approveArtifact(artifact_type: 'spec' | 'plan'): Promise<ArtifactApproveResponse> {
  return request('/artifacts/approve', {
    method: 'POST',
    body: JSON.stringify({ artifact_type }),
  }, 'admin')
}

export function revokeArtifactApproval(artifact_type: string): Promise<{ artifact_type: string; approved: boolean }> {
  return request(`/artifacts/approve?artifact_type=${encodeURIComponent(artifact_type)}`, {
    method: 'DELETE',
  }, 'admin')
}

// ---- Workflow Metrics ----

export function fetchWorkflowMetrics(): Promise<WorkflowMetrics> {
  return request('/metrics/workflow')
}

// ---- Task Search ----

export function searchTasks(query: string, limit = 10): Promise<TaskSearchResponse> {
  return request('/tasks/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  })
}
