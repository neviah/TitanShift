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

// ---- Skills Market ----

export interface SkillMarketItem {
  id: string
  name: string
  description: string
  version: string
  mode: string
  domain: string
  required_tools: string[]
  dependencies: string[]
  installable: boolean
  installed: boolean
  missing_tools: string[]
  tags: string[]
}

export interface MarketRemoteStatus {
  last_synced_at: string | null
  source: string | null
  pulled_count: number
  index_hash: string
  signing_version: string
}

export interface UiMarketOverviewResponse {
  total_listed: number
  installed_count: number
  installable_count: number
  non_installable_count: number
  remote_status: MarketRemoteStatus | null
  recent_events: Record<string, unknown>[]
}

// ---- Skills List ----

export interface SkillDefinition {
  id: string
  name: string
  description: string
  mode: string
  domain: string
  required_tools: string[]
  dependencies: string[]
  prompt_template?: string
  tags: string[]
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

// ---- Health ----

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error'
  version: string
  uptime_seconds: number
  components: Record<string, { status: string; detail?: string }>
}
