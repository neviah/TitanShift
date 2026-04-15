import { useMemo } from 'react'
import { fetchLogs, fetchTaskDetail, fetchTasks } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './CurrentRunTab.module.css'

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : []
}

export function CurrentRunTab() {
  const { data: tasks, loading, error } = usePolling(fetchTasks, { interval: 5000 })
  const newestTask = useMemo(() => {
    const rows = (tasks ?? []).slice()
    rows.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    return rows[0] ?? null
  }, [tasks])

  const { data: taskDetail } = usePolling(
    () => (newestTask ? fetchTaskDetail(newestTask.task_id) : Promise.resolve(null)),
    { interval: 5000 },
  )
  const { data: logs } = usePolling(() => fetchLogs(40), { interval: 5000 })

  const recentEvents = useMemo(() => {
    return (logs?.items ?? [])
      .filter((entry) => {
        const eventType = String(entry.event_type ?? '').toLowerCase()
        return eventType.includes('task_') || eventType.includes('workflow_')
      })
      .slice(0, 8)
  }, [logs])

  if (loading) return <p className={styles.hint}>Loading current run...</p>
  if (error) return <p className={`${styles.hint} text-error`}>{error}</p>

  return (
    <div className={styles.root}>
      <div className={styles.card}>
        <p className={styles.title}>Current Run</p>
        {!newestTask && <p className={styles.hint}>No tasks yet.</p>}
        {newestTask && (
          <>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Task</span>
              <span className={`${styles.rowValue} font-mono`}>{newestTask.task_id}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Status</span>
              <span className={`badge ${newestTask.status === 'completed' ? 'badge-ok' : newestTask.status === 'failed' ? 'badge-error' : 'badge-warn'}`}>
                {newestTask.status}
              </span>
            </div>
            {typeof taskDetail?.output?.workflow_mode === 'string' && (
              <div className={styles.row}>
                <span className={styles.rowLabel}>Workflow</span>
                <span className="badge badge-dim">{String(taskDetail.output.workflow_mode)}</span>
              </div>
            )}
            {readStringArray(taskDetail?.output?.used_tools).length > 0 && (
              <div className={styles.toolsBlock}>
                <span className={styles.rowLabel}>Tools Used</span>
                <div className={styles.inlineBadges}>
                  {readStringArray(taskDetail?.output?.used_tools).map((toolName, index) => (
                    <span key={`${toolName}-${index}`} className="badge badge-dim">{toolName}</span>
                  ))}
                </div>
              </div>
            )}
            {readStringArray(taskDetail?.output?.requested_tools).length > 0 && (
              <div className={styles.toolsBlock}>
                <span className={styles.rowLabel}>Requested Tools</span>
                <div className={styles.inlineBadges}>
                  {readStringArray(taskDetail?.output?.requested_tools).map((toolName, index) => (
                    <span key={`${toolName}-${index}`} className="badge badge-warn">{toolName}</span>
                  ))}
                </div>
              </div>
            )}
            {typeof taskDetail?.output?.fallback_used === 'boolean' && (
              <div className={styles.row}>
                <span className={styles.rowLabel}>Fallback Used</span>
                <span className={`badge ${taskDetail.output.fallback_used ? 'badge-warn' : 'badge-ok'}`}>
                  {taskDetail.output.fallback_used ? 'yes' : 'no'}
                </span>
              </div>
            )}
            {typeof taskDetail?.output?.primary_failure_reason === 'string' && taskDetail.output.primary_failure_reason.length > 0 && (
              <p className={`${styles.hint} text-error`}>{String(taskDetail.output.primary_failure_reason)}</p>
            )}
            {readStringArray(taskDetail?.output?.missing_approvals).length > 0 && (
              <div className={styles.inlineBadges}>
                {readStringArray(taskDetail?.output?.missing_approvals).map((approval) => (
                  <span key={approval} className="badge badge-error">{approval}</span>
                ))}
              </div>
            )}
            {typeof newestTask.error === 'string' && newestTask.error.length > 0 && (
              <p className={`${styles.hint} text-error`}>{newestTask.error}</p>
            )}
          </>
        )}
      </div>

      <div className={styles.card}>
        <p className={styles.title}>Timeline Pulse</p>
        <div className={styles.list}>
          {recentEvents.map((entry, index) => (
            <div key={`${entry.timestamp}-${entry.event_type}-${index}`} className={styles.eventRow}>
              <span className={styles.pulseDot} />
              <span className={styles.eventName}>{entry.event_type}</span>
              <span className={styles.eventTime}>{new Date(entry.timestamp).toLocaleTimeString()}</span>
            </div>
          ))}
          {recentEvents.length === 0 && <p className={styles.hint}>No recent workflow events.</p>}
        </div>
      </div>
    </div>
  )
}
