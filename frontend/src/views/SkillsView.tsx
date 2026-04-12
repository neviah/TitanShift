import { useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import { fetchMarketList, installSkill, uninstallSkill } from '../api/client'
import type { SkillMarketItem } from '../api/types'
import styles from './SkillsView.module.css'
import { Download, Trash2, Zap, AlertTriangle } from 'lucide-react'

export function SkillsView() {
  const { data, loading, error, refresh } = usePolling(fetchMarketList, { interval: 30000 })
  const [busyId, setBusyId] = useState<string | null>(null)

  async function handleInstall(skill: SkillMarketItem) {
    setBusyId(skill.id)
    try {
      await installSkill(skill.id)
      refresh()
    } finally {
      setBusyId(null)
    }
  }

  async function handleUninstall(skill: SkillMarketItem) {
    setBusyId(skill.id)
    try {
      await uninstallSkill(skill.id)
      refresh()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <h2 className={styles.title}>Skills Market</h2>
        <button className={styles.refreshBtn} onClick={refresh}>Refresh</button>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}

      {data && (
        <ul className={styles.list}>
          {data.map((skill) => (
            <li key={skill.id} className={styles.item}>
              <div className={styles.itemLeft}>
                <div className={styles.skillHeader}>
                  <Zap size={14} className={skill.installed ? 'text-accent' : 'text-muted'} />
                  <span className={styles.skillName}>{skill.name}</span>
                  <span className={`badge badge-dim`}>{skill.version}</span>
                  {skill.installed && <span className="badge badge-ok">installed</span>}
                </div>
                <p className={styles.desc}>{skill.description}</p>
                {skill.missing_tools.length > 0 && (
                  <div className={styles.missing}>
                    <AlertTriangle size={12} />
                    <span>Missing: {skill.missing_tools.join(', ')}</span>
                  </div>
                )}
              </div>
              <div className={styles.actions}>
                {skill.installed ? (
                  <button
                    className={`${styles.btn} ${styles.btnDanger}`}
                    onClick={() => handleUninstall(skill)}
                    disabled={busyId === skill.id}
                    title="Uninstall"
                  >
                    <Trash2 size={13} />
                  </button>
                ) : (
                  <button
                    className={`${styles.btn} ${styles.btnPrimary}`}
                    onClick={() => handleInstall(skill)}
                    disabled={!skill.installable || busyId === skill.id}
                    title={skill.installable ? 'Install' : 'Missing required tools'}
                  >
                    <Download size={13} />
                  </button>
                )}
              </div>
            </li>
          ))}
          {data.length === 0 && (
            <p className={styles.hint}>No skills in market. Sync a remote source first.</p>
          )}
        </ul>
      )}
    </div>
  )
}
