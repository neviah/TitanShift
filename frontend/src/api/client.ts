import type {
  UiIngestionOverviewResponse,
  UiMarketOverviewResponse,
  HealthResponse,
  SkillMarketItem,
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
  RuntimeSkillSummary,
  SkillRepoIntakeResponse,
  SkillRepoIntakeUninstallResponse,
  TaskCancelResponse,
  TaskRollbackResponse,
  ApiKeyStatusResponse,
  ApiKeyRotateResponse,
} from './types'

export const API_BASE = '/api'

type AuthScope = 'read' | 'admin'

const LOCAL_READ_KEY = 'titanshift-api-key'
const LOCAL_ADMIN_KEY = 'titanshift-admin-api-key'

function isLocalhost(): boolean {
  if (typeof window === 'undefined') return false
  return window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost'
}

function getStoredApiKey(scope: AuthScope): string {
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

function deriveSkillName(skillId: string): string {
  const cleaned = skillId.trim()
  if (!cleaned) return 'Untitled skill'
  return cleaned
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

async function request<T>(path: string, init?: RequestInit, authScope: AuthScope = 'read'): Promise<T> {
  const apiKey = getStoredApiKey(authScope)
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
      ...init?.headers,
    },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

// ---- UI overview ----

export function fetchIngestionOverview(): Promise<UiIngestionOverviewResponse> {
  return request('/ui/ingestion/overview')
}

export function fetchMarketOverview(): Promise<UiMarketOverviewResponse> {
  return request('/ui/market/overview')
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

// ---- Market ----

export function fetchMarketList(): Promise<SkillMarketItem[]> {
  return request<Array<Record<string, unknown>>>('/skills/market').then((rows) => (
    rows.map((row) => {
      const skillId = String(row.skill_id ?? row.id ?? '').trim()
      const name = String(row.name ?? '').trim() || deriveSkillName(skillId)
      return {
        id: skillId,
        name,
        description: String(row.description ?? ''),
        version: String(row.version ?? '0.1.0'),
        mode: String(row.mode ?? 'prompt'),
        domain: String(row.domain ?? 'general'),
        required_tools: Array.isArray(row.required_tools) ? row.required_tools.map(String) : [],
        dependencies: Array.isArray(row.dependencies) ? row.dependencies.map(String) : [],
        installable: Boolean(row.installable),
        installed: Boolean(row.installed),
        missing_tools: Array.isArray(row.missing_tools) ? row.missing_tools.map(String) : [],
        tags: Array.isArray(row.tags) ? row.tags.map(String) : [],
      } satisfies SkillMarketItem
    })
  ))
}

export function fetchRuntimeSkills(): Promise<RuntimeSkillSummary[]> {
  return request<Array<Record<string, unknown>>>('/skills').then((rows) => (
    rows.map((row) => ({
      skill_id: String(row.skill_id ?? ''),
      description: String(row.description ?? ''),
      mode: String(row.mode ?? 'prompt'),
      domain: String(row.domain ?? 'general'),
      version: String(row.version ?? '0.1.0'),
      tags: Array.isArray(row.tags) ? row.tags.map(String) : [],
      required_tools: Array.isArray(row.required_tools) ? row.required_tools.map(String) : [],
      ranking_score: typeof row.ranking_score === 'number' ? row.ranking_score : undefined,
    } satisfies RuntimeSkillSummary))
  ))
}

export function installSkill(skillId: string): Promise<unknown> {
  return request('/skills/market/install', {
    method: 'POST',
    body: JSON.stringify({ skill_id: skillId }),
  }, 'admin')
}

export function uninstallSkill(skillId: string): Promise<unknown> {
  return request('/skills/market/uninstall', {
    method: 'POST',
    body: JSON.stringify({ skill_id: skillId }),
  }, 'admin')
}

export function syncRemoteMarket(source: string): Promise<unknown> {
  return request('/skills/market/remote/sync', {
    method: 'POST',
    body: JSON.stringify({ source, force: true }),
  }, 'admin')
}

export function intakeSkillRepo(
  repo_url: string,
  auto_install = true,
  trust_policy = 'github_only',
): Promise<SkillRepoIntakeResponse> {
  return request('/skills/repo-intake', {
    method: 'POST',
    body: JSON.stringify({ repo_url, auto_install, trust_policy }),
  }, 'admin')
}

export function uninstallRepoIntakeSkill(skill_id: string): Promise<SkillRepoIntakeUninstallResponse> {
  return request('/skills/repo-intake/uninstall', {
    method: 'POST',
    body: JSON.stringify({ skill_id }),
  }, 'admin')
}

// ---- Chat ----

export function sendChat(requestBody: ChatRequest): Promise<ChatResponse> {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify(requestBody),
  })
}

export function fetchTasks(): Promise<TaskSummary[]> {
  return request('/tasks')
}

export function fetchAgents(): Promise<AgentSummary[]> {
  return request('/agents')
}

export function fetchRoleTemplates(): Promise<RoleTemplate[]> {
  return request('/roles/templates')
}

export function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
  return request(`/tasks/${taskId}`)
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

// ---- API Key Management ----

export function fetchApiKeyStatus(): Promise<ApiKeyStatusResponse> {
  return request('/api-keys/status', {}, 'admin')
}

export function rotateApiKey(scope: 'read' | 'admin'): Promise<ApiKeyRotateResponse> {
  return request(`/api-keys/rotate?scope=${scope}`, { method: 'POST' }, 'admin')
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
