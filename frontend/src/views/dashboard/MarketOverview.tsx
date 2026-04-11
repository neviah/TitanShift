import { usePolling } from '../../hooks/usePolling'
import { fetchMarketOverview } from '../../api/client'
import styles from './MarketOverview.module.css'
import { RefreshCw } from 'lucide-react'

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
        </>
      )}
    </div>
  )
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
