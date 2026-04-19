import { useMemo } from 'react'
import { fetchAgents, fetchConfig } from '../../../api/client'
import { usePolling } from '../../../hooks/usePolling'
import styles from './AgentTab.module.css'

export function AgentTab() {
  const { data: agents, loading, error } = usePolling(fetchAgents, { interval: 8000 })
  const { data: config } = usePolling(fetchConfig, { interval: 12000 })

  const rootAgent = useMemo(() => {
    const rows = agents ?? []
    return rows.find((a) => !a.spawned_from_task) ?? rows[0]
  }, [agents])

  const children = useMemo(() => {
    if (!rootAgent) return []
    return (agents ?? []).filter((a) => a.agent_id !== rootAgent.agent_id && a.active)
  }, [agents, rootAgent])

  if (loading) return <p className={styles.empty}>Loading agents...</p>
  if (error) return <p className={`${styles.empty} text-error`}>{error}</p>

  return (
    <div className={styles.root}>
      <section className={styles.section}>
        <h3 className={styles.heading}>Active Agent</h3>
        <div className={styles.card}>
          <div className={styles.row}>
            <span className={styles.label}>Name</span>
            <span className={styles.value}>{rootAgent?.role ?? 'orchestrator'}</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Status</span>
            <span className={`badge ${rootAgent?.active ? 'badge-ok' : 'badge-warn'}`}>{rootAgent?.active ? 'active' : 'idle'}</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Model</span>
            <span className={`${styles.value} font-mono`}>{rootAgent?.model_default_backend ?? 'local_stub'}</span>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Agent Tree</h3>
        <div className={styles.card}>
          <div className={styles.row}>
            <span className={styles.label}>Root</span>
            <span className={`${styles.value} font-mono`}>{rootAgent?.agent_id ?? 'none'}</span>
          </div>
          {children.slice(0, 8).map((agent) => (
            <div key={agent.agent_id} className={styles.row}>
              <span className={styles.label}>{agent.role}</span>
              <span className={`${styles.value} font-mono`}>{agent.agent_id}</span>
            </div>
          ))}
          {children.length === 0 && <p className={styles.empty}>No spawned sub-agents</p>}
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Budget Defaults</h3>
        <div className={styles.card}>
          <div className={styles.row}>
            <span className={styles.label}>Steps</span>
            <span className={styles.value}>{Number(config?.['state_machine.default_budget.max_steps'] ?? 1)}</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Tokens</span>
            <span className={styles.value}>{Number(config?.['state_machine.default_budget.max_tokens'] ?? 8192)}</span>
          </div>
        </div>
      </section>
    </div>
  )
}
