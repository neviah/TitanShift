import { fetchLogs } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './DataTab.module.css'

export function LogsTab() {
  const { data, loading, error } = usePolling(() => fetchLogs(20), { interval: 8000 })

  if (loading) return <p className={styles.hint}>Loading logs...</p>
  if (error) return <p className={`${styles.hint} text-error`}>{error}</p>

  return (
    <div className={styles.root}>
      <div className={styles.card}>
        <p className={styles.title}>Recent Events</p>
        <div className={styles.list}>
          {(data?.items ?? []).slice(0, 16).map((entry, idx) => (
            <div key={`${entry.timestamp}-${entry.event_type}-${idx}`} className={styles.row}>
              <span className={styles.rowLabel}>{entry.event_type}</span>
              <span className={styles.rowMeta}>{new Date(entry.timestamp).toLocaleTimeString()}</span>
            </div>
          ))}
          {(data?.items ?? []).length === 0 && <p className={styles.hint}>No recent events.</p>}
        </div>
      </div>
    </div>
  )
}
