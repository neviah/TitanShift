import { useMemo, useState } from 'react'
import { Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  createSchedulerTemplateJob,
  deleteSchedulerTemplateJob,
  fetchSchedulerJobs,
  fetchSchedulerTemplateJobs,
  fetchTaskTemplates,
} from '../api/client'
import { usePolling } from '../hooks/usePolling'
import styles from './SchedulerView.module.css'

export function SchedulerView() {
  const { data: templates, loading: loadingTemplates, error: templatesError, refresh: refreshTemplates } = usePolling(fetchTaskTemplates, { interval: 8000 })
  const { data: templateJobs, loading: loadingTemplateJobs, error: templateJobsError, refresh: refreshTemplateJobs } = usePolling(fetchSchedulerTemplateJobs, { interval: 5000 })
  const { data: schedulerJobs, loading: loadingJobs, error: jobsError, refresh: refreshJobs } = usePolling(fetchSchedulerJobs, { interval: 5000 })

  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [intervalSeconds, setIntervalSeconds] = useState(300)
  const [jobId, setJobId] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const templateRows = templates ?? []
  const selectedTemplate = useMemo(
    () => templateRows.find((t) => t.template_id === selectedTemplateId) ?? null,
    [templateRows, selectedTemplateId],
  )

  async function handleCreateBinding() {
    if (!selectedTemplateId) {
      setError('Select a task template first.')
      return
    }
    setCreating(true)
    setError(null)
    setFeedback(null)
    try {
      const payload = {
        template_id: selectedTemplateId,
        schedule_type: 'interval' as const,
        interval_seconds: intervalSeconds,
        enabled: true,
        ...(jobId.trim() ? { job_id: jobId.trim() } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      }
      const created = await createSchedulerTemplateJob(payload)
      setFeedback(`Created scheduler binding: ${created.job_id}`)
      setJobId('')
      setDescription('')
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
                    {template.name}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.field}>
              <span>Interval (s)</span>
              <input
                type="number"
                min={1}
                step={1}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Math.max(1, Number(e.target.value) || 1))}
              />
            </label>

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
                  template: {job.template_id} • every {job.interval_seconds}s • {job.enabled ? 'enabled' : 'disabled'}
                </p>
              </div>
              <button
                className={styles.iconBtn}
                title="Delete template scheduler job"
                onClick={() => handleDeleteBinding(job.job_id)}
                disabled={deleteId === job.job_id}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <h3>Scheduler Runtime Jobs</h3>
            <span className={styles.badge}>{(schedulerJobs ?? []).length} total</span>
          </header>
          <div className={styles.jobListCompact}>
            {(schedulerJobs ?? []).slice(0, 10).map((job) => (
              <div key={job.job_id} className={styles.jobCompactRow}>
                <span className={styles.jobTitle}>{job.job_id}</span>
                <span className={`badge ${job.enabled ? 'badge-ok' : 'badge-error'}`}>{job.enabled ? 'enabled' : 'disabled'}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
