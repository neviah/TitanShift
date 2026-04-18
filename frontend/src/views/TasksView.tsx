import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchTasks, fetchTaskDetail, fetchWorkflowMetrics, searchTasks } from '../api/client'
import type { TaskSummary, TaskDetail, WorkflowMetrics } from '../api/types'
import styles from './TasksView.module.css'

type Tab = 'history' | 'metrics'

// ── helpers ─────────────────────────────────────────────────────────────────

function statusDotClass(status: string): string {
  if (status === 'completed') return styles.dotCompleted
  if (status === 'failed') return styles.dotFailed
  if (status === 'running') return styles.dotRunning
  return styles.dotPending
}

function statusBadgeClass(status: string): string {
  if (status === 'completed') return styles.badgeSuccess
  if (status === 'failed') return styles.badgeFailed
  if (status === 'running') return styles.badgeRunning
  return styles.badgePending
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function fmtPct(rate: number | null | undefined): string {
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(1)}%`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// ── sub-components ───────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: string | number
  unit?: string
}
function StatCard({ label, value, unit }: StatCardProps) {
  return (
    <div className={styles.statCard}>
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue}>
        {value}
        {unit && <span className={styles.statUnit}>{unit}</span>}
      </div>
    </div>
  )
}

// ── TasksView ────────────────────────────────────────────────────────────────

export function TasksView() {
  const [activeTab, setActiveTab] = useState<Tab>('history')

  // ── history state ──────────────────────────────────────────────────────────
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loadingTasks, setLoadingTasks] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<TaskSummary[] | null>(null)
  const [searching, setSearching] = useState(false)

  // ── metrics state ──────────────────────────────────────────────────────────
  const [metrics, setMetrics] = useState<WorkflowMetrics | null>(null)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [metricsError, setMetricsError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  // Load task list
  const loadTasks = useCallback(() => {
    setLoadingTasks(true)
    fetchTasks()
      .then((rows) => setTasks(rows))
      .catch(() => {})
      .finally(() => setLoadingTasks(false))
  }, [])

  // Load metrics
  const loadMetrics = useCallback(() => {
    setLoadingMetrics(true)
    setMetricsError(null)
    fetchWorkflowMetrics()
      .then((m) => setMetrics(m))
      .catch((e: unknown) => setMetricsError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingMetrics(false))
  }, [])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  useEffect(() => {
    if (activeTab === 'metrics') loadMetrics()
  }, [activeTab, loadMetrics])

  // Load task detail when a task card is clicked
  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    setLoadingDetail(true)
    fetchTaskDetail(selectedId)
      .then((d) => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoadingDetail(false))
  }, [selectedId])

  // Search handler
  function handleSearch() {
    const q = searchQuery.trim()
    if (!q) {
      setSearchResults(null)
      return
    }
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setSearching(true)
    searchTasks(q, 20)
      .then((resp) => {
        // Map search results back to TaskSummary shape for the list renderer
        const mapped: TaskSummary[] = resp.results.map((r) => ({
          task_id: r.task_id,
          description: r.description,
          status: r.status,
          created_at: '',
          started_at: null,
          completed_at: null,
          success: r.success,
        }))
        setSearchResults(mapped)
      })
      .catch(() => setSearchResults(null))
      .finally(() => setSearching(false))
  }

  function clearSearch() {
    setSearchQuery('')
    setSearchResults(null)
  }

  const displayedTasks = searchResults ?? tasks

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className={styles.root}>
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${activeTab === 'history' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('history')}
        >
          Run History
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'metrics' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('metrics')}
        >
          Metrics
        </button>
      </div>

      {/* ── Run History tab ──────────────────────────────────────────────── */}
      {activeTab === 'history' && (
        <div className={styles.historyPanel}>
          <div className={styles.searchRow}>
            <input
              className={styles.searchInput}
              placeholder="Search past runs…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
            />
            {searchResults ? (
              <button className={styles.searchBtn} onClick={clearSearch}>Clear</button>
            ) : (
              <button className={styles.searchBtn} onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
                {searching ? '…' : 'Search'}
              </button>
            )}
          </div>

          {loadingTasks && !tasks.length && (
            <p className={styles.empty}>Loading…</p>
          )}

          <div className={styles.taskList}>
            {displayedTasks.length === 0 && !loadingTasks && (
              <p className={styles.empty}>
                {searchResults ? 'No matching tasks.' : 'No runs yet.'}
              </p>
            )}
            {displayedTasks.map((t) => (
              <div key={t.task_id}>
                <div
                  className={styles.taskCard}
                  onClick={() => setSelectedId(selectedId === t.task_id ? null : t.task_id)}
                >
                  <div className={styles.taskHeader}>
                    <span className={`${styles.statusDot} ${statusDotClass(t.status)}`} />
                    <span className={styles.taskDesc}>{t.description}</span>
                    <span className={`${styles.badge} ${statusBadgeClass(t.status)}`}>{t.status}</span>
                  </div>
                  <div className={styles.taskMeta}>
                    <span>{t.task_id.slice(0, 12)}…</span>
                    {t.completed_at && <span>Completed {fmtDate(t.completed_at)}</span>}
                    {!t.completed_at && t.created_at && <span>Created {fmtDate(t.created_at)}</span>}
                  </div>
                </div>

                {/* Inline detail drawer */}
                {selectedId === t.task_id && (
                  <div className={styles.drawer}>
                    <div className={styles.drawerTitle}>
                      Task detail
                      <button className={styles.drawerClose} onClick={() => setSelectedId(null)}>✕</button>
                    </div>
                    {loadingDetail && <p className={styles.empty}>Loading…</p>}
                    {detail && !loadingDetail && (
                      <pre className={styles.outputPre}>
                        {JSON.stringify(
                          {
                            task_id: detail.task_id,
                            status: detail.status,
                            success: detail.success,
                            error: detail.error ?? undefined,
                            created_at: detail.created_at,
                            completed_at: detail.completed_at ?? undefined,
                            response: (detail.output as Record<string, unknown>)?.['response'],
                            workflow_mode: (detail.output as Record<string, unknown>)?.['workflow_mode'],
                            used_tools: (detail.output as Record<string, unknown>)?.['used_tools'],
                            created_paths: (detail.output as Record<string, unknown>)?.['created_paths'],
                            updated_paths: (detail.output as Record<string, unknown>)?.['updated_paths'],
                          },
                          null,
                          2,
                        )}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Metrics tab ──────────────────────────────────────────────────── */}
      {activeTab === 'metrics' && (
        <div className={styles.metricsPanel}>
          <div className={styles.metricsHeader}>
            <span className={styles.sectionTitle}>Workflow metrics</span>
            <button className={styles.refreshBtn} onClick={loadMetrics} disabled={loadingMetrics}>
              {loadingMetrics ? 'Loading…' : '↻ Refresh'}
            </button>
          </div>

          {metricsError && <p className={styles.empty} style={{ color: 'var(--error)' }}>{metricsError}</p>}

          {metrics && (
            <>
              <span className={styles.sectionTitle}>Overall</span>
              <div className={styles.metricsRow}>
                <StatCard label="Total runs" value={metrics.total_tasks} />
                <StatCard label="Successful" value={metrics.total_successful_tasks ?? '—'} />
                <StatCard label="Failed" value={metrics.total_failed_tasks ?? '—'} />
                <StatCard label="Success rate" value={fmtPct(metrics.overall_success_rate)} />
              </div>

              <span className={styles.sectionTitle}>Lightning mode</span>
              <div className={styles.metricsRow}>
                <StatCard label="Total" value={metrics.lightning.total_tasks} />
                <StatCard label="Success rate" value={fmtPct(metrics.lightning.success_rate)} />
                <StatCard label="Avg duration" value={fmtMs(metrics.lightning.avg_duration_ms)} />
                <StatCard label="p50 duration" value={fmtMs(metrics.lightning.p50_duration_ms)} />
                <StatCard label="p95 duration" value={fmtMs(metrics.lightning.p95_duration_ms)} />
              </div>

              <span className={styles.sectionTitle}>Superpowered mode</span>
              <div className={styles.metricsRow}>
                <StatCard label="Total" value={metrics.superpowered.total_tasks} />
                <StatCard label="Success rate" value={fmtPct(metrics.superpowered.success_rate)} />
                <StatCard label="Avg duration" value={fmtMs(metrics.superpowered.avg_duration_ms)} />
                <StatCard label="p50 duration" value={fmtMs(metrics.superpowered.p50_duration_ms)} />
                <StatCard label="p95 duration" value={fmtMs(metrics.superpowered.p95_duration_ms)} />
                <StatCard label="Gate blocks" value={metrics.superpowered.gate_blocked_count} />
                <StatCard label="Reviews ran" value={metrics.superpowered.review_ran_count} />
                <StatCard label="Review pass rate" value={fmtPct(metrics.superpowered.review_pass_rate)} />
                <StatCard label="Avg iterations" value={metrics.superpowered.avg_review_iterations?.toFixed(1) ?? '—'} />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
