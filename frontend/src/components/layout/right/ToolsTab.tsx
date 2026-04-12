import { fetchTools } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './DataTab.module.css'

export function ToolsTab() {
  const { data, loading, error } = usePolling(fetchTools, { interval: 15000 })

  if (loading) return <p className={styles.hint}>Loading tools...</p>
  if (error) return <p className={`${styles.hint} text-error`}>{error}</p>

  const allowedCount = (data ?? []).filter((t) => t.allowed_by_policy).length

  return (
    <div className={styles.root}>
      <div className={styles.card}>
        <p className={styles.title}>Tool Policy</p>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Allowed</span>
          <span className="badge badge-ok">{allowedCount}</span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Blocked</span>
          <span className="badge badge-error">{Math.max(0, (data ?? []).length - allowedCount)}</span>
        </div>
      </div>

      <div className={styles.card}>
        <p className={styles.title}>Toolset</p>
        <div className={styles.list}>
          {(data ?? []).slice(0, 14).map((tool) => (
            <div key={tool.name} className={styles.row}>
              <span className={styles.rowLabel}>{tool.name}</span>
              <span className={`badge ${tool.allowed_by_policy ? 'badge-ok' : 'badge-error'}`}>
                {tool.allowed_by_policy ? 'allowed' : 'blocked'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
