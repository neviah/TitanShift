import { useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import { fetchMarketList, fetchRuntimeSkills, installSkill, uninstallSkill } from '../api/client'
import type { SkillMarketItem } from '../api/types'
import styles from './SkillsView.module.css'
import { Download, Trash2, Zap, AlertTriangle, Sparkles, Wrench } from 'lucide-react'

export function SkillsView() {
  const { data, loading, error, refresh } = usePolling(fetchMarketList, { interval: 30000 })
  const { data: runtimeData, loading: runtimeLoading, error: runtimeError, refresh: refreshRuntime } = usePolling(fetchRuntimeSkills, { interval: 30000 })
  const [busyId, setBusyId] = useState<string | null>(null)
  const builtinSkills = (runtimeData ?? []).filter((skill) => skill.tags.includes('builtin'))
  const runtimeSkills = (runtimeData ?? []).filter((skill) => !skill.tags.includes('builtin'))

  async function handleInstall(skill: SkillMarketItem) {
    setBusyId(skill.id)
    try {
      await installSkill(skill.id)
      refresh()
      refreshRuntime()
    } finally {
      setBusyId(null)
    }
  }

  async function handleUninstall(skill: SkillMarketItem) {
    setBusyId(skill.id)
    try {
      await uninstallSkill(skill.id)
      refresh()
      refreshRuntime()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <h2 className={styles.title}>Skills Market</h2>
        <button className={styles.refreshBtn} onClick={() => { refresh(); refreshRuntime() }}>Refresh</button>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}
      {runtimeLoading && <p className={styles.hint}>Loading runtime skills…</p>}
      {runtimeError && <p className={`${styles.hint} text-error`}>{runtimeError}</p>}

      {builtinSkills.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.sectionTitle}>Built-In Workflow Skills</h3>
            <p className={styles.sectionHint}>These are the prompt-injected workflow skills the orchestrator uses internally.</p>
          </div>
          <ul className={styles.list}>
            {builtinSkills.map((skill) => (
              <li key={skill.skill_id} className={styles.item}>
                <div className={styles.itemLeft}>
                  <div className={styles.skillHeader}>
                    <Sparkles size={14} className="text-accent" />
                    <span className={styles.skillName}>{skill.skill_id}</span>
                    <span className="badge badge-ok">builtin</span>
                    <span className="badge badge-dim">{skill.mode}</span>
                  </div>
                  <p className={styles.desc}>{skill.description}</p>
                  <div className={styles.metaRow}>
                    {skill.required_tools.map((tool) => (
                      <span key={`${skill.skill_id}-${tool}`} className="badge badge-dim">{tool}</span>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {runtimeSkills.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.sectionTitle}>Runtime Skills</h3>
            <p className={styles.sectionHint}>Registered skills currently available to the harness runtime.</p>
          </div>
          <ul className={styles.list}>
            {runtimeSkills.map((skill) => (
              <li key={skill.skill_id} className={styles.item}>
                <div className={styles.itemLeft}>
                  <div className={styles.skillHeader}>
                    <Wrench size={14} className="text-muted" />
                    <span className={styles.skillName}>{skill.skill_id}</span>
                    <span className="badge badge-dim">{skill.mode}</span>
                    <span className="badge badge-dim">{skill.domain}</span>
                  </div>
                  <p className={styles.desc}>{skill.description}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.sectionTitle}>Marketplace Skills</h3>
            <p className={styles.sectionHint}>Installable skill packages and optional tool-backed extensions.</p>
          </div>
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
        </div>
      )}
    </div>
  )
}
