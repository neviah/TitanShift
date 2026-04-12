import { fetchMemorySummary } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './DataTab.module.css'

export function MemoryTab() {
  const { data, loading, error } = usePolling(fetchMemorySummary, { interval: 15000 })

  if (loading) return <p className={styles.hint}>Loading memory...</p>
  if (error) return <p className={`${styles.hint} text-error`}>{error}</p>
  if (!data) return <p className={styles.hint}>No memory metrics.</p>

  return (
    <div className={styles.root}>
      <div className={styles.card}>
        <p className={styles.title}>Memory Layers</p>
        <div className={styles.row}><span className={styles.rowLabel}>Working entries</span><span className={styles.rowMeta}>{data.working_entries}</span></div>
        <div className={styles.row}><span className={styles.rowLabel}>Short-term entries</span><span className={styles.rowMeta}>{data.short_term_entries}</span></div>
        <div className={styles.row}><span className={styles.rowLabel}>Long-term entries</span><span className={styles.rowMeta}>{data.long_term_entries}</span></div>
      </div>
      <div className={styles.card}>
        <p className={styles.title}>Scopes</p>
        <div className={styles.row}><span className={styles.rowLabel}>Working agents</span><span className={styles.rowMeta}>{data.working_agents}</span></div>
        <div className={styles.row}><span className={styles.rowLabel}>Short-term agents</span><span className={styles.rowMeta}>{data.short_term_agents}</span></div>
        <div className={styles.row}><span className={styles.rowLabel}>Long-term scopes</span><span className={styles.rowMeta}>{data.long_term_scopes}</span></div>
      </div>
    </div>
  )
}
