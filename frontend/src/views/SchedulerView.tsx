import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Pause, Play, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import {
  createSchedulerTaskStack,
  deleteSchedulerTaskStack,
  fetchSchedulerJobs,
  fetchSchedulerTaskStacks,
  fetchTasks,
  setSchedulerJobEnabled,
  triggerSchedulerTick,
} from '../api/client'
import { usePolling } from '../hooks/usePolling'
import type { SchedulerJob, TaskSummary } from '../api/types'
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

function compactTaskLabel(task: TaskSummary): string {
  const summary = task.description.replace(/\s+/g, ' ').trim()
  return summary.length > 64 ? `${summary.slice(0, 61)}...` : summary
}

export function SchedulerView() {
  const { data: tasks, loading: loadingTasks, error: tasksError, refresh: refreshTasks } = usePolling(fetchTasks, { interval: 6000 })
  const { data: taskStacks, loading: loadingTaskStacks, error: taskStacksError, refresh: refreshTaskStacks } = usePolling(fetchSchedulerTaskStacks, { interval: 5000 })
  const { data: schedulerJobs, loading: loadingJobs, error: jobsError, refresh: refreshJobs } = usePolling(fetchSchedulerJobs, { interval: 5000 })

  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [taskStack, setTaskStack] = useState<string[]>([])
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

  const rawTaskRows = tasks ?? []
  const taskRows = useMemo(() => {
    const seen = new Set<string>()
    const rows: TaskSummary[] = []
    for (const task of rawTaskRows) {
      // Hide scheduler-generated internal step tasks from the selection list.
      if (task.task_id.includes(':step-')) continue
      const key = task.description.trim().toLowerCase()
      if (!key || seen.has(key)) continue
      seen.add(key)
      rows.push(task)
    }
    return rows
  }, [rawTaskRows])
  const taskById = useMemo(() => new Map(taskRows.map((t) => [t.task_id, t])), [taskRows])
  const schedulerById = useMemo(() => new Map((schedulerJobs ?? []).map((job) => [job.job_id, job])), [schedulerJobs])

  useEffect(() => {
    const handle = window.setInterval(() => {
      void triggerSchedulerTick()
        .then(() => {
          refreshTaskStacks()
          refreshJobs()
        })
        .catch(() => {
          // keep scheduler UI readable if admin key is unavailable
        })
    }, 5000)
    return () => window.clearInterval(handle)
  }, [refreshJobs, refreshTaskStacks])

  function addTaskToStack() {
    if (!selectedTaskId) return
    setTaskStack((prev) => [...prev, selectedTaskId])
  }

  function removeTaskAt(index: number) {
    setTaskStack((prev) => prev.filter((_, i) => i !== index))
  }

  function moveTask(index: number, direction: -1 | 1) {
    setTaskStack((prev) => {
      const nextIndex = index + direction
      if (nextIndex < 0 || nextIndex >= prev.length) return prev
      const next = prev.slice()
      const [moved] = next.splice(index, 1)
      next.splice(nextIndex, 0, moved)
      return next
    })
  }

  async function handleCreateStackJob() {
    if (taskStack.length === 0) {
      setError('Add at least one task to the stack first.')
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
        task_ids: taskStack,
        schedule_type: scheduleType,
        interval_seconds: Math.max(1, intervalMinutes) * 60,
        ...(cron ? { cron } : {}),
        enabled: true,
        ...(jobId.trim() ? { job_id: jobId.trim() } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      }
      const created = await createSchedulerTaskStack(payload)
      setFeedback(`Created scheduled task stack: ${created.job_id}`)
      setJobId('')
      setDescription('')
      setTaskStack([])
      await triggerSchedulerTick().catch(() => undefined)
      refreshTaskStacks()
      refreshJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleDeleteTaskStack(jobIdToDelete: string) {
    setDeleteId(jobIdToDelete)
    setError(null)
    setFeedback(null)
    try {
      await deleteSchedulerTaskStack(jobIdToDelete)
      setFeedback(`Removed scheduled task stack: ${jobIdToDelete}`)
      refreshTaskStacks()
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
      refreshTaskStacks()
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
            refreshTasks()
            refreshTaskStacks()
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
            <h3>Build Scheduled Task Stack</h3>
            <span className={styles.badge}>{taskRows.length} unique tasks</span>
          </header>

          {(tasksError || taskStacksError || jobsError || error) && (
            <p className={`${styles.hint} text-error`}>{tasksError || taskStacksError || jobsError || error}</p>
          )}
          {feedback && <p className={`${styles.hint} text-ok`}>{feedback}</p>}

          <div className={styles.formGrid}>
            <div className={styles.taskPickerRow}>
              <label className={styles.field}>
                <span>Select Existing Task</span>
                <select value={selectedTaskId} onChange={(e) => setSelectedTaskId(e.target.value)}>
                  <option value="">Select task</option>
                  {taskRows.map((task) => (
                    <option key={task.task_id} value={task.task_id}>
                      {compactTaskLabel(task)} ({task.task_id.slice(0, 8)})
                    </option>
                  ))}
                </select>
              </label>
              <button className={styles.primaryBtn} onClick={addTaskToStack} disabled={!selectedTaskId}>
                <Plus size={14} />
                Add To Stack
              </button>
            </div>

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
                placeholder="task-stack-news"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
              />
            </label>

            <label className={styles.field}>
              <span>Description (optional)</span>
              <input
                type="text"
                placeholder="Collect site summaries"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>

          <div className={styles.jobListCompact}>
            {taskStack.length === 0 ? (
              <p className={styles.hint}>No tasks in stack yet. Pick a task and press Add To Stack.</p>
            ) : (
              taskStack.map((taskId, index) => (
                <div key={`${taskId}-${index}`} className={styles.jobCompactRow}>
                  <span className={styles.jobTitle}>{index + 1}. {compactTaskLabel(taskById.get(taskId) ?? { task_id: taskId, description: taskId, status: '', created_at: '' })}</span>
                  <div className={styles.actions}>
                    <button className={styles.iconBtn} onClick={() => moveTask(index, -1)} disabled={index === 0} title="Move up">
                      <ArrowUp size={14} />
                    </button>
                    <button className={styles.iconBtn} onClick={() => moveTask(index, 1)} disabled={index === taskStack.length - 1} title="Move down">
                      <ArrowDown size={14} />
                    </button>
                    <button className={styles.iconBtn} onClick={() => removeTaskAt(index)} title="Remove from stack">
                      <X size={14} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className={styles.actions}>
            <button className={styles.primaryBtn} onClick={handleCreateStackJob} disabled={creating || taskStack.length === 0}>
              <Plus size={14} />
              {creating ? 'Creating...' : 'Create Scheduled Stack'}
            </button>
          </div>
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <h3>Scheduled Task Stacks</h3>
            <span className={styles.badge}>{(taskStacks ?? []).length} active</span>
          </header>

          {(loadingTasks || loadingTaskStacks || loadingJobs) && <p className={styles.hint}>Loading scheduler data...</p>}
          {(taskStacks ?? []).length === 0 && !loadingTaskStacks && (
            <p className={styles.hint}>No scheduled task stacks yet. Build one above.</p>
          )}

          {(taskStacks ?? []).map((job) => {
            const runtimeJob = schedulerById.get(job.job_id)
            return (
              <div key={job.job_id} className={styles.jobRow}>
                <div className={styles.jobMeta}>
                  <p className={styles.jobTitle}>{job.job_id}</p>
                  <p className={styles.jobSub}>
                    {scheduleLabel(job)} • {job.enabled ? 'enabled' : 'disabled'} • {job.steps.length} tasks
                  </p>
                  {runtimeJob && (
                    <p className={styles.jobSub}>
                      {runtimeJob.is_running ? 'running now' : `next run in ${formatCountdown(runtimeJob.next_run_at)}`}
                    </p>
                  )}
                </div>
                <div className={styles.actions}>
                  {runtimeJob && (
                    <button
                      className={styles.iconBtn}
                      title={runtimeJob.enabled ? 'Disable runtime job' : 'Enable runtime job'}
                      onClick={() => handleToggleRuntimeJob(runtimeJob)}
                      disabled={toggleId === job.job_id}
                    >
                      {runtimeJob.enabled ? <Pause size={14} /> : <Play size={14} />}
                    </button>
                  )}
                  <button
                    className={styles.iconBtn}
                    title="Delete scheduled task stack"
                    onClick={() => handleDeleteTaskStack(job.job_id)}
                    disabled={deleteId === job.job_id}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )
          })}
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
