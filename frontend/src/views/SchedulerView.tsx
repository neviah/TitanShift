import { useEffect, useMemo, useState } from 'react'
import { Pause, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  createSchedulerTemplateJob,
  deleteSchedulerTemplateJob,
  fetchSchedulerJobs,
  fetchSchedulerTemplateJobs,
  fetchTaskTemplates,
  setSchedulerJobEnabled,
  triggerSchedulerTick,
} from '../api/client'
import { usePolling } from '../hooks/usePolling'
import type { SchedulerJob } from '../api/types'
import styles from './SchedulerView.module.css'

function formatCountdown(nextRunAt?: string | null): string {
  if (!nextRunAt) return 'n/a'
  const ts = Date.parse(nextRunAt)
  if (!Number.isFinite(ts)) return 'n/a'
  const deltaMs = Math.max(0, ts - Date.now())
  const totalSeconds = Math.round(deltaMs / 1000)
  const mm = Math.floor(totalSeconds / 60)
  const ss = totalSeconds % 60
  return `${mm}m ${ss}s`
}

function scheduleLabel(job: { schedule_type: string; interval_seconds: number; cron?: string | null }): string {
  if (job.schedule_type === 'cron') return `cron: ${job.cron ?? '* * * * *'}`
  const minutes = Math.max(1, Math.round((job.interval_seconds ?? 60) / 60))
  return `every ${minutes}m`
}

function buildWeeklyCron(dayToken: string, timeHHmm: string): string {
  const [hourRaw, minuteRaw] = timeHHmm.split(':')
  const hour = Number(hourRaw)
  const minute = Number(minuteRaw)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return '0 10 * * 0'
  const h = Math.max(0, Math.min(23, hour))
  const m = Math.max(0, Math.min(59, minute))
  return `${m} ${h} * * ${dayToken}`
}

export function SchedulerView() {
  const { data: templates, loading: loadingTemplates, error: templatesError, refresh: refreshTemplates } = usePolling(fetchTaskTemplates, { interval: 8000 })
  const { data: templateJobs, loading: loadingTemplateJobs, error: templateJobsError, refresh: refreshTemplateJobs } = usePolling(fetchSchedulerTemplateJobs, { interval: 5000 })
  const { data: schedulerJobs, loading: loadingJobs, error: jobsError, refresh: refreshJobs } = usePolling(fetchSchedulerJobs, { interval: 5000 })

  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [scheduleType, setScheduleType] = useState<'interval' | 'cron'>('interval')
  const [intervalMinutes, setIntervalMinutes] = useState(5)
  const [cronExpression, setCronExpression] = useState('')
  const [cronDay, setCronDay] = useState('0')
  const [cronTime, setCronTime] = useState('10:00')
  const [jobId, setJobId] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [toggleId, setToggleId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const templateRows = templates ?? []
  const templateById = useMemo(() => new Map(templateRows.map((t) => [t.template_id, t])), [templateRows])
  const schedulerById = useMemo(() => new Map((schedulerJobs ?? []).map((job) => [job.job_id, job])), [schedulerJobs])
  const selectedTemplate = useMemo(
    () => templateRows.find((t) => t.template_id === selectedTemplateId) ?? null,
    [templateRows, selectedTemplateId],
  )

  useEffect(() => {
    const handle = window.setInterval(() => {
      void triggerSchedulerTick()
        .then(() => {
          refreshTemplateJobs()
          refreshJobs()
        })
        .catch(() => {
          // Keep scheduler UI readable if admin key is unavailable.
        })
    }, 5000)
    return () => window.clearInterval(handle)
  }, [refreshJobs, refreshTemplateJobs])

  async function handleCreateBinding() {
    if (!selectedTemplateId) {
      setError('Select a task template first.')
      return
    }
    setCreating(true)
    setError(null)
    setFeedback(null)
    try {
      const cron = scheduleType === 'cron'
        ? (cronExpression.trim() || buildWeeklyCron(cronDay, cronTime))
        : undefined
      const payload = {
        template_id: selectedTemplateId,
        schedule_type: scheduleType,
        interval_seconds: Math.max(1, intervalMinutes) * 60,
        ...(cron ? { cron } : {}),
        enabled: true,
        ...(jobId.trim() ? { job_id: jobId.trim() } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      }
      const created = await createSchedulerTemplateJob(payload)
      setFeedback(`Created scheduler binding: ${created.job_id}`)
      setJobId('')
      setDescription('')
      await triggerSchedulerTick().catch(() => undefined)
      refreshTemplateJobs()
      refreshJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleDeleteBinding(id: string) {
    setDeleteId(id)
    setError(null)
    setFeedback(null)
    try {
      await deleteSchedulerTemplateJob(id)
      setFeedback(`Removed scheduler binding: ${id}`)
      refreshTemplateJobs()
      refreshJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleteId(null)
    }
  }

  async function handleToggleRuntimeJob(job: SchedulerJob) {
    setToggleId(job.job_id)
    setError(null)
    setFeedback(null)
    try {
      const updated = await setSchedulerJobEnabled(job.job_id, !job.enabled)
      setFeedback(`${updated.job_id} is now ${updated.enabled ? 'enabled' : 'disabled'}`)
      refreshTemplateJobs()
      refreshJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setToggleId(null)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.topBar}>
        <h2 className={styles.pageTitle}>Scheduler</h2>
        <button
          className={styles.refreshBtn}
          onClick={() => {
            refreshTemplates()
            refreshTemplateJobs()
            refreshJobs()
          }}
          title="Refresh scheduler state"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <div className={styles.content}>
        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <h3>Bind Template To Scheduler</h3>
            <span className={styles.badge}>{templateRows.length} templates</span>
          </header>

          {(templatesError || templateJobsError || jobsError || error) && (
            <p className={`${styles.hint} text-error`}>{templatesError || templateJobsError || jobsError || error}</p>
          )}
          {feedback && <p className={`${styles.hint} text-ok`}>{feedback}</p>}

          <div className={styles.formGrid}>
            <label className={styles.field}>
              <span>Template</span>
              <select value={selectedTemplateId} onChange={(e) => setSelectedTemplateId(e.target.value)}>
                <option value="">Select template</option>
                {templateRows.map((template) => (
                  <option key={template.template_id} value={template.template_id}>
                    {template.name} ({template.template_id.slice(-6)})
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.field}>
              <span>Schedule</span>
              <select value={scheduleType} onChange={(e) => setScheduleType(e.target.value === 'cron' ? 'cron' : 'interval')}>
                <option value="interval">Interval (minutes)</option>
                <option value="cron">Cron (day/time)</option>
              </select>
            </label>

            {scheduleType === 'interval' ? (
              <label className={styles.field}>
                <span>Interval (minutes)</span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={intervalMinutes}
                  onChange={(e) => setIntervalMinutes(Math.max(1, Number(e.target.value) || 1))}
                />
              </label>
            ) : (
              <>
                <label className={styles.field}>
                  <span>Day</span>
                  <select value={cronDay} onChange={(e) => setCronDay(e.target.value)}>
                    <option value="0">Sunday</option>
                    <option value="1">Monday</option>
                    <option value="2">Tuesday</option>
                    <option value="3">Wednesday</option>
                    <option value="4">Thursday</option>
                    <option value="5">Friday</option>
                    <option value="6">Saturday</option>
                  </select>
                </label>
                <label className={styles.field}>
                  <span>Time</span>
                  <input type="time" value={cronTime} onChange={(e) => setCronTime(e.target.value)} />
                </label>
                <label className={styles.field}>
                  <span>Cron override (optional)</span>
                  <input
                    type="text"
                    placeholder="0 10 * * 0"
                    value={cronExpression}
                    onChange={(e) => setCronExpression(e.target.value)}
                  />
                </label>
              </>
            )}

            <label className={styles.field}>
              <span>Job ID (optional)</span>
              <input
                type="text"
                placeholder="tmpl-job-weather"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
              />
            </label>

            <label className={styles.field}>
              <span>Description (optional)</span>
              <input
                type="text"
                placeholder="Run weather widget template"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>

          <div className={styles.actions}>
            <button className={styles.primaryBtn} onClick={handleCreateBinding} disabled={creating || !selectedTemplateId}>
              <Plus size={14} />
              {creating ? 'Binding...' : 'Create Binding +'}
            </button>
          </div>

          {selectedTemplate && (
            <p className={styles.hint}>
              Selected: <strong>{selectedTemplate.name}</strong> ({selectedTemplate.workflow_mode} / {selectedTemplate.model_backend})
            </p>
          )}
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <h3>Template Jobs</h3>
            <span className={styles.badge}>{(templateJobs ?? []).length} active</span>
          </header>

          {(loadingTemplates || loadingTemplateJobs || loadingJobs) && <p className={styles.hint}>Loading scheduler data...</p>}
          {(templateJobs ?? []).length === 0 && !loadingTemplateJobs && (
            <p className={styles.hint}>No template jobs yet. Use the + button above to create one.</p>
          )}

          {(templateJobs ?? []).map((job) => (
            <div key={job.job_id} className={styles.jobRow}>
              <div className={styles.jobMeta}>
                <p className={styles.jobTitle}>{job.job_id}</p>
                <p className={styles.jobSub}>
                  template: {templateById.get(job.template_id)?.name ?? job.template_id} • {scheduleLabel(job)} • {job.enabled ? 'enabled' : 'disabled'}
                </p>
                {schedulerById.get(job.job_id) && (
                  <p className={styles.jobSub}>
                    {schedulerById.get(job.job_id)?.is_running
                      ? 'running now'
                      : `next run in ${formatCountdown(schedulerById.get(job.job_id)?.next_run_at)}`}
                  </p>
                )}
              </div>
              <div className={styles.actions}>
                {schedulerById.get(job.job_id) && (
                  <button
                    className={styles.iconBtn}
                    title={schedulerById.get(job.job_id)?.enabled ? 'Disable runtime job' : 'Enable runtime job'}
                    onClick={() => handleToggleRuntimeJob(schedulerById.get(job.job_id)!)}
                    disabled={toggleId === job.job_id}
                  >
                    {schedulerById.get(job.job_id)?.enabled ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                )}
                <button
                  className={styles.iconBtn}
                  title="Delete template scheduler job"
                  onClick={() => handleDeleteBinding(job.job_id)}
                  disabled={deleteId === job.job_id}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <h3>Scheduler Runtime Jobs</h3>
            <span className={styles.badge}>{(schedulerJobs ?? []).length} total</span>
          </header>
          <div className={styles.jobListCompact}>
            {(schedulerJobs ?? []).slice(0, 20).map((job) => (
              <div key={job.job_id} className={styles.jobCompactRow}>
                <span className={styles.jobTitle}>{job.job_id}</span>
                <span className={`badge ${job.is_running ? 'badge-warn' : (job.enabled ? 'badge-ok' : 'badge-error')}`}>
                  {job.is_running ? 'running' : (job.enabled ? 'enabled' : 'disabled')}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
