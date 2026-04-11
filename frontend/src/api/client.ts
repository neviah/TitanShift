import type {
  UiIngestionOverviewResponse,
  UiMarketOverviewResponse,
  HealthResponse,
  SkillMarketItem,
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

// ---- Health ----

export function fetchHealth(): Promise<HealthResponse> {
  return request('/health')
}

// ---- Market ----

export function fetchMarketList(): Promise<{ items: SkillMarketItem[] }> {
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
