import { usePolling } from '../../../hooks/usePolling'
import { fetchHealth } from '../../../api/client'
import styles from './HealthTab.module.css'

export function HealthTab() {
  const { data, error, loading } = usePolling(fetchHealth, { interval: 10000 })

  if (loading) return <p className={styles.status}>Loading…</p>
  if (error) return <p className={`${styles.status} text-error`}>Error: {error}</p>

  const overallClass =
    data?.status === 'ok' ? 'badge-ok' : data?.status === 'degraded' ? 'badge-warn' : 'badge-error'

  return (
    <div className={styles.root}>
      <div className={styles.overall}>
        <span className={`badge ${overallClass}`}>{data?.status ?? '—'}</span>
        <span className={styles.version}>{data?.version}</span>
      </div>

      <div className={styles.metric}>
        <span className={styles.label}>Uptime</span>
        <span className={`${styles.value} font-mono`}>
          {data?.uptime_seconds != null ? formatUptime(data.uptime_seconds) : '—'}
        </span>
      </div>

      {data?.components && Object.keys(data.components).length > 0 && (
        <section>
          <h3 className={styles.heading}>Components</h3>
          {Object.entries(data.components).map(([name, info]) => {
            const cls =
              info.status === 'ok' ? 'badge-ok' : info.status === 'degraded' ? 'badge-warn' : 'badge-error'
            return (
              <div key={name} className={styles.component}>
                <span className={styles.compName}>{name}</span>
                <span className={`badge ${cls}`}>{info.status}</span>
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}
