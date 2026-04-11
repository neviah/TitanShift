import { usePolling } from '../../hooks/usePolling'
import { fetchIngestionOverview } from '../../api/client'
import styles from './IngestionOverview.module.css'
import { RefreshCw } from 'lucide-react'

export function IngestionOverview() {
  const { data, error, loading, refresh } = usePolling(fetchIngestionOverview, { interval: 10000 })

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.title}>Ingestion</span>
        <button className={styles.refreshBtn} onClick={refresh} title="Refresh">
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}

      {data && (
        <>
          <div className={styles.grid}>
            <Stat label="Total Ingested"  value={data.stats.total_ingested} />
            <Stat label="Deduplicated"    value={data.stats.total_deduplicated} />
            <Stat label="Embeddings"      value={data.stats.total_embeddings} accent />
          </div>

          {data.recent_ingestions.length > 0 && (
            <section>
              <h4 className={styles.sectionTitle}>Recent</h4>
              <ul className={styles.list}>
                {data.recent_ingestions.slice(0, 5).map((ev) => (
                  <li key={ev.id} className={styles.item}>
                    <span className={styles.source}>{ev.source}</span>
                    <span className={`badge ${ev.status === 'ok' ? 'badge-ok' : 'badge-warn'}`}>
                      {ev.status}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  const cls = accent ? 'text-accent' : 'text-primary'
  return (
    <div className={styles.stat}>
      <span className={`${styles.statValue} ${cls}`}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}
