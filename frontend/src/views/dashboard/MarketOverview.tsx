import { usePolling } from '../../hooks/usePolling'
import { fetchMarketOverview } from '../../api/client'
import styles from './MarketOverview.module.css'
import { RefreshCw } from 'lucide-react'

type MarketOverviewEvent = {
  timestamp?: string
  event_type?: string
  payload?: Record<string, unknown>
}

export function MarketOverview() {
  const { data, error, loading, refresh } = usePolling(fetchMarketOverview, { interval: 15000 })

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.title}>Skill Market</span>
        <button className={styles.refreshBtn} onClick={refresh} title="Refresh">
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}

      {data && (
        <>
          <div className={styles.grid}>
            <Stat label="Total Listed"   value={data.total_listed} />
            <Stat label="Installed"      value={data.installed_count} accent />
            <Stat label="Installable"    value={data.installable_count} />
            <Stat label="Missing Tools"  value={data.non_installable_count} warn={data.non_installable_count > 0} />
          </div>

          {data.remote_status && (
            <div className={styles.remote}>
              <span className={styles.remoteLabel}>Last sync</span>
              <span className={`${styles.remoteValue} font-mono`}>
                {data.remote_status.last_synced_at
                  ? new Date(data.remote_status.last_synced_at).toLocaleTimeString()
                  : 'never'}
              </span>
              <span className={`badge ${data.remote_status.signing_version === 'v2-ed25519' ? 'badge-ok' : 'badge-warn'}`}>
                {data.remote_status.signing_version || 'none'}
              </span>
            </div>
          )}

          {data.recent_events.length > 0 && (
            <section className={styles.eventsSection}>
              <h4 className={styles.sectionTitle}>Recent Market Events</h4>
              <ul className={styles.eventList}>
                {data.recent_events.slice(0, 6).map((rawEvent, index) => {
                  const event = rawEvent as MarketOverviewEvent
                  const eventType = event.event_type ?? 'UNKNOWN_EVENT'
                  const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : 'unknown'
                  return (
                    <li key={`${event.timestamp ?? 'event'}-${eventType}-${index}`} className={styles.eventItem}>
                      <div className={styles.eventCopy}>
                        <span className={styles.eventType}>{formatEventType(eventType)}</span>
                        <span className={styles.eventSummary}>{summarizeEvent(event)}</span>
                      </div>
                      <span className={styles.eventTime}>{timestamp}</span>
                    </li>
                  )
                })}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function formatEventType(eventType: string): string {
  return eventType
    .replace(/^SKILL_/, '')
    .replace(/^MARKET_/, '')
    .replace(/^REPO_/, '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function summarizeEvent(event: MarketOverviewEvent): string {
  const payload = event.payload ?? {}
  const skillId = String(payload.skill_id ?? payload.installed_skill_id ?? '').trim()
  const repoName = String(payload.repo_name ?? '').trim()
  const removedTools = Array.isArray(payload.removed_tool_ids) ? payload.removed_tool_ids.length : 0
  const generatedTools = Array.isArray(payload.generated_tool_ids) ? payload.generated_tool_ids.length : 0

  switch (event.event_type) {
    case 'SKILL_REPO_INTAKE':
      return `${repoName || skillId || 'Repo'} installed with ${generatedTools} generated tool${generatedTools === 1 ? '' : 's'}`
    case 'SKILL_REPO_UNINSTALL_CASCADE':
      return `${skillId || 'Repo integration'} removed ${removedTools} generated tool${removedTools === 1 ? '' : 's'}`
    case 'SKILL_MARKET_INSTALL':
      return `${skillId || 'Skill'} installed`
    case 'SKILL_MARKET_UNINSTALL':
      return `${skillId || 'Skill'} uninstalled`
    case 'SKILL_MARKET_UPDATE':
      return `${skillId || 'Skill'} updated`
    case 'SKILL_MARKET_REMOTE_SYNC':
      return `Synced ${String(payload.pulled_count ?? 0)} remote market item${Number(payload.pulled_count ?? 0) === 1 ? '' : 's'}`
    default:
      return skillId || repoName || 'Event recorded'
  }
}

function Stat({
  label,
  value,
  accent,
  warn,
}: {
  label: string
  value: number
  accent?: boolean
  warn?: boolean
}) {
  const cls = accent ? 'text-accent' : warn ? 'text-warn' : 'text-primary'
  return (
    <div className={styles.stat}>
      <span className={`${styles.statValue} ${cls}`}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}
