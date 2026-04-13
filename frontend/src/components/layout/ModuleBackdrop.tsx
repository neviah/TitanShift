import { useMemo } from 'react'
import { usePolling } from '../../hooks/usePolling'
import { fetchLogs, fetchStatus } from '../../api/client'
import styles from './ModuleBackdrop.module.css'

export function ModuleBackdrop() {
  const { data } = usePolling(fetchStatus, { interval: 12000 })
  const { data: logs } = usePolling(() => fetchLogs(40), { interval: 4000 })

  const modules = useMemo(() => {
    const fromHealth = (data?.health ?? []).map((h) => h.name)
    const loaded = data?.loaded_modules ?? []
    const merged = Array.from(new Set([...fromHealth, ...loaded]))
    return merged.slice(0, 18)
  }, [data])

  const activeModuleNames = useMemo(() => {
    const candidates = new Set<string>()
    const known = modules.map((name) => name.toLowerCase())
    for (const item of logs?.items ?? []) {
      const payloadStr = JSON.stringify(item.payload ?? {}).toLowerCase()
      const eventStr = String(item.event_type ?? '').toLowerCase()
      for (const moduleName of known) {
        if (payloadStr.includes(moduleName) || eventStr.includes(moduleName)) {
          candidates.add(moduleName)
        }
      }
    }
    return candidates
  }, [logs, modules])

  return (
    <div className={styles.root} aria-hidden>
      {modules.map((name, idx) => {
        const isActive = activeModuleNames.has(name.toLowerCase())
        const statusClass = isActive ? styles.active : styles.idle
        const left = 8 + ((idx * 17) % 84)
        const top = 10 + ((idx * 23) % 76)
        const delay = `${(idx % 7) * 0.35}s`
        return (
          <div
            key={`${name}-${idx}`}
            className={`${styles.node} ${statusClass}`}
            style={{ left: `${left}%`, top: `${top}%`, animationDelay: delay }}
            title={name}
          >
            <span className={styles.label}>{name}</span>
          </div>
        )
      })}
    </div>
  )
}
