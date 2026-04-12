import { useMemo } from 'react'
import { fetchMarketList } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './DataTab.module.css'

export function SkillsTab() {
  const { data, loading, error } = usePolling(fetchMarketList, { interval: 15000 })
  const installed = useMemo(() => (data ?? []).filter((s) => s.installed), [data])

  if (loading) return <p className={styles.hint}>Loading skills...</p>
  if (error) return <p className={`${styles.hint} text-error`}>{error}</p>

  return (
    <div className={styles.root}>
      <div className={styles.card}>
        <p className={styles.title}>Skill Coverage</p>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Installed</span>
          <span className="badge badge-ok">{installed.length}</span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Available</span>
          <span className="badge badge-dim">{(data ?? []).length}</span>
        </div>
      </div>

      <div className={styles.card}>
        <p className={styles.title}>Assigned Candidates</p>
        <div className={styles.list}>
          {installed.slice(0, 12).map((skill) => (
            <div key={skill.id} className={styles.row}>
              <span className={styles.rowLabel}>{skill.name}</span>
              <span className="badge badge-dim">{skill.version}</span>
            </div>
          ))}
          {installed.length === 0 && <p className={styles.hint}>No installed skills yet.</p>}
        </div>
      </div>
    </div>
  )
}
