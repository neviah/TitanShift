import type {
  UiIngestionOverviewResponse,
  UiMarketOverviewResponse,
  HealthResponse,
  SkillMarketItem,
  ChatRequest,
  ChatResponse,
  TaskSummary,
  TaskDetail,
  WorkspaceTreeNode,
  WorkspaceFileResponse,
  ToolSummary,
  MemorySummary,
  AgentSummary,
  LogQueryResponse,
  GraphifyRequest,
  GraphifyResponse,
} from './types'

const API_BASE = '/api'

function deriveSkillName(skillId: string): string {
  const cleaned = skillId.trim()
  if (!cleaned) return 'Untitled skill'
  return cleaned
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
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
  })
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
  })
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

export function installSkill(skillId: string): Promise<unknown> {
  return request('/skills/market/install', {
    method: 'POST',
    body: JSON.stringify({ skill_id: skillId }),
  })
}

export function uninstallSkill(skillId: string): Promise<unknown> {
  return request('/skills/market/uninstall', {
    method: 'POST',
    body: JSON.stringify({ skill_id: skillId }),
  })
}

export function syncRemoteMarket(source: string): Promise<unknown> {
  return request('/skills/market/remote/sync', {
    method: 'POST',
    body: JSON.stringify({ source, force: true }),
  })
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

export function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
  return request(`/tasks/${taskId}`)
}

export function fetchWorkspaceTree(): Promise<WorkspaceTreeNode[]> {
  return request('/workspace/tree')
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
