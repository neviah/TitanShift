import type {
  UiIngestionOverviewResponse,
  UiMarketOverviewResponse,
  HealthResponse,
  SkillMarketItem,
  ChatRequest,
  ChatResponse,
  TaskSummary,
} from './types'

const API_BASE = '/api'

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
  return request('/skills/market')
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
