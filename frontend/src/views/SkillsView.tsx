import { useMemo, useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import { fetchRuntimeSkills, intakeSkillRepo, uninstallRepoIntakeSkill } from '../api/client'
import type { RuntimeSkillSummary, SkillRepoIntakeResponse } from '../api/types'
import styles from './SkillsView.module.css'
import { Sparkles, Wrench, Link2, Send, Bot, Trash2 } from 'lucide-react'

export function SkillsView() {
  const { data: runtimeData, loading: runtimeLoading, error: runtimeError, refresh: refreshRuntime } = usePolling(fetchRuntimeSkills, { interval: 30000 })
  const [repoUrl, setRepoUrl] = useState('')
  const [autoInstall, setAutoInstall] = useState(true)
  const [trustPolicy, setTrustPolicy] = useState('github_only')
  const [intakeBusy, setIntakeBusy] = useState(false)
  const [intakeError, setIntakeError] = useState<string | null>(null)
  const [intakeResult, setIntakeResult] = useState<SkillRepoIntakeResponse | null>(null)
  const [uninstallBusySkill, setUninstallBusySkill] = useState<string | null>(null)
  const [uninstallError, setUninstallError] = useState<string | null>(null)

  const builtinSkills = useMemo(
    () => (runtimeData ?? []).filter((skill) => skill.tags.includes('builtin')),
    [runtimeData],
  )
  const runtimeSkills = useMemo(
    () => (runtimeData ?? []).filter((skill) => !skill.tags.includes('builtin')),
    [runtimeData],
  )
  const allSkills: RuntimeSkillSummary[] = useMemo(
    () => [...builtinSkills, ...runtimeSkills],
    [builtinSkills, runtimeSkills],
  )

  async function handleIntakeSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = repoUrl.trim()
    if (!trimmed) {
      setIntakeError('Paste a repository URL first.')
      return
    }
    setIntakeBusy(true)
    setIntakeError(null)
    try {
      const result = await intakeSkillRepo(trimmed, autoInstall, trustPolicy)
      setIntakeResult(result)
      await refreshRuntime()
    } catch (err) {
      setIntakeError(err instanceof Error ? err.message : String(err))
      setIntakeResult(null)
    } finally {
      setIntakeBusy(false)
    }
  }

  async function handleRepoUninstall(skillId: string) {
    if (!skillId.trim()) return
    setUninstallBusySkill(skillId)
    setUninstallError(null)
    try {
      await uninstallRepoIntakeSkill(skillId)
      await refreshRuntime()
      if (intakeResult?.installed_skill_id === skillId) {
        setIntakeResult(null)
      }
    } catch (err) {
      setUninstallError(err instanceof Error ? err.message : String(err))
    } finally {
      setUninstallBusySkill(null)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <h2 className={styles.title}>Skills Control Center</h2>
        <button className={styles.refreshBtn} onClick={() => { void refreshRuntime() }}>Refresh</button>
      </div>

      {runtimeLoading && <p className={styles.hint}>Loading runtime skills…</p>}
      {runtimeError && <p className={`${styles.hint} text-error`}>{runtimeError}</p>}

      <div className={`${styles.section} ${styles.intakeSection}`}>
        <div className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>Add Skill/Tool Repo</h3>
          <p className={styles.sectionHint}>Paste a repository URL and TitanShift will classify and scaffold an install-ready integration skill.</p>
        </div>

        <form className={styles.intakeForm} onSubmit={handleIntakeSubmit}>
          <div className={styles.intakeRow}>
            <div className={styles.inputWrap}>
              <Link2 size={14} className="text-muted" />
              <input
                type="url"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
              />
            </div>
            <button className={`${styles.btn} ${styles.btnPrimary} ${styles.submitBtn}`} type="submit" disabled={intakeBusy}>
              <Send size={13} />
              {intakeBusy ? 'Processing…' : 'Submit'}
            </button>
          </div>
          <label className={styles.autoInstallRow}>
            <input
              type="checkbox"
              checked={autoInstall}
              onChange={(e) => setAutoInstall(e.target.checked)}
            />
            Auto-install generated integration skill
          </label>
          <label className={styles.autoInstallRow}>
            <span>Trust policy:</span>
            <select value={trustPolicy} onChange={(e) => setTrustPolicy(e.target.value)}>
              <option value="github_only">GitHub only</option>
              <option value="public_github_only">Public GitHub only</option>
              <option value="org_only">Organization-owned only</option>
              <option value="trusted_owner">Trusted owner allowlist</option>
              <option value="allow_all">Allow all</option>
            </select>
          </label>
        </form>

        {intakeError && <p className={`${styles.hint} text-error`}>{intakeError}</p>}
        {uninstallError && <p className={`${styles.hint} text-error`}>{uninstallError}</p>}

        <div className={styles.processPanel}>
          <div className={styles.processHeader}>
            <Bot size={14} className="text-accent" />
            <span>Repo Intake Process</span>
          </div>

          {intakeResult ? (
            <>
              <div className={styles.resultMeta}>
                <span className="badge badge-dim">{intakeResult.classification}</span>
                <span className="badge badge-dim">recommended: {intakeResult.recommended_artifact}</span>
                <span className="badge badge-dim">confidence {(intakeResult.confidence * 100).toFixed(0)}%</span>
                {intakeResult.trust_policy && <span className="badge badge-dim">trust: {intakeResult.trust_policy}</span>}
                {typeof intakeResult.trust_passed === 'boolean' && (
                  <span className={intakeResult.trust_passed ? 'badge badge-ok' : 'badge badge-warn'}>
                    trust {intakeResult.trust_passed ? 'passed' : 'failed'}
                  </span>
                )}
                {intakeResult.installed_skill_id && <span className="badge badge-ok">installed: {intakeResult.installed_skill_id}</span>}
                {(intakeResult.generated_tool_ids ?? []).length > 0 && (
                  <span className="badge badge-ok">tools: {(intakeResult.generated_tool_ids ?? []).length}</span>
                )}
              </div>
              {intakeResult.installed_skill_id && (
                <div className={styles.resultActions}>
                  <button
                    className={`${styles.btn} ${styles.btnDanger} ${styles.submitBtn}`}
                    type="button"
                    disabled={uninstallBusySkill === intakeResult.installed_skill_id}
                    onClick={() => { void handleRepoUninstall(intakeResult.installed_skill_id ?? '') }}
                  >
                    <Trash2 size={13} />
                    {uninstallBusySkill === intakeResult.installed_skill_id ? 'Uninstalling…' : 'Uninstall This Repo Integration'}
                  </button>
                </div>
              )}
              <ul className={styles.processList}>
                {intakeResult.process_log.map((line, index) => (
                  <li key={`line-${index}`}>{line}</li>
                ))}
              </ul>
              {(intakeResult.generated_tool_ids ?? []).length > 0 && (
                <ul className={styles.notesList}>
                  {(intakeResult.generated_tool_ids ?? []).map((toolId, index) => (
                    <li key={`tool-${index}`}>Generated tool: {toolId}</li>
                  ))}
                </ul>
              )}
              {intakeResult.notes.length > 0 && (
                <ul className={styles.notesList}>
                  {intakeResult.notes.map((line, index) => (
                    <li key={`note-${index}`}>{line}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className={styles.hint}>Submit a repo URL to see classification and install results.</p>
          )}
        </div>
      </div>

      <div className={`${styles.section} ${styles.skillsSection}`}>
        <div className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>Installed Skills</h3>
          <p className={styles.sectionHint}>Runtime-available skills in this workspace.</p>
        </div>
        <ul className={styles.list}>
          {allSkills.map((skill) => (
            <li key={skill.skill_id} className={styles.item}>
              <div className={styles.itemLeft}>
                <div className={styles.skillHeader}>
                  {skill.tags.includes('builtin') ? <Sparkles size={14} className="text-accent" /> : <Wrench size={14} className="text-muted" />}
                  <span className={styles.skillName}>{skill.skill_id}</span>
                  {skill.tags.includes('builtin') && <span className="badge badge-ok">builtin</span>}
                  <span className="badge badge-dim">{skill.mode}</span>
                  <span className="badge badge-dim">{skill.domain}</span>
                </div>
                <p className={styles.desc}>{skill.description}</p>
                {skill.required_tools.length > 0 && (
                  <div className={styles.metaRow}>
                    {skill.required_tools.map((tool) => (
                      <span key={`${skill.skill_id}-${tool}`} className="badge badge-dim">{tool}</span>
                    ))}
                  </div>
                )}
              </div>
              {skill.tags.includes('repo-intake') && !skill.tags.includes('builtin') && (
                <div className={styles.actions}>
                  <button
                    className={`${styles.btn} ${styles.btnDanger}`}
                    type="button"
                    title="Uninstall repo-intake skill and generated tools"
                    disabled={uninstallBusySkill === skill.skill_id}
                    onClick={() => { void handleRepoUninstall(skill.skill_id) }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              )}
            </li>
          ))}
          {allSkills.length === 0 && (
            <p className={styles.hint}>No runtime skills found in this workspace.</p>
          )}
        </ul>
      </div>
    </div>
  )
}
