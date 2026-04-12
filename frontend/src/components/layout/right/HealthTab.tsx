import { usePolling } from '../../../hooks/usePolling'
import { fetchStatus } from '../../../api/client'
import styles from './HealthTab.module.css'

export function HealthTab() {
  const { data, error, loading } = usePolling(fetchStatus, { interval: 10000 })

  if (loading) return <p className={styles.status}>Loading…</p>
  if (error) return <p className={`${styles.status} text-error`}>Error: {error}</p>

  const overallOk = data?.ok
  const overallCls = overallOk ? 'badge-ok' : 'badge-error'

  return (
    <div className={styles.root}>
      <div className={styles.overall}>
        <span className={`badge ${overallCls}`}>{overallOk ? 'ok' : 'error'}</span>
      </div>

      <div className={styles.metric}>
        <span className={styles.label}>Model backend</span>
        <span className={`${styles.value} font-mono`}>{data?.default_model_backend ?? '—'}</span>
      </div>
      <div className={styles.metric}>
        <span className={styles.label}>Graph</span>
        <span className={`${styles.value} font-mono`}>{data?.graph_backend ?? '—'}</span>
      </div>
      <div className={styles.metric}>
        <span className={styles.label}>Semantic</span>
        <span className={`${styles.value} font-mono`}>{data?.semantic_backend ?? '—'}</span>
      </div>
      <div className={styles.metric}>
        <span className={styles.label}>Subagents</span>
        <span className={`badge ${data?.subagents_enabled ? 'badge-ok' : 'badge-dim'}`}>
          {data?.subagents_enabled ? 'on' : 'off'}
        </span>
      </div>

      {data && data.health.length > 0 && (
        <section>
          <h3 className={styles.heading}>Components</h3>
          {data.health.map((rec) => {
            const status = rec.status.toLowerCase()
            const cls =
              status === 'ok' || status === 'healthy' || status === 'up' ? 'badge-ok'
              : status === 'degraded' || status === 'warning' || status === 'warn' ? 'badge-warn'
              : 'badge-error'
            return (
              <div key={rec.name} className={styles.component}>
                <span className={styles.compName}>{rec.name}</span>
                <span className={`badge ${cls}`}>{rec.status}</span>
              </div>
            )
          })}
        </section>
      )}

      {data && data.health.length === 0 && (
        <p className={`${styles.status} text-muted`}>No component records yet</p>
      )}

      {data?.loaded_modules && data.loaded_modules.length > 0 && (
        <section>
          <h3 className={styles.heading}>Loaded Modules</h3>
          {data.loaded_modules.slice(0, 12).map((name) => (
            <div key={name} className={styles.component}>
              <span className={styles.compName}>{name}</span>
              <span className="badge badge-dim">loaded</span>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
