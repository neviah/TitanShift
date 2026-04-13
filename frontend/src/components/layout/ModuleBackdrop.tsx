import { useMemo } from 'react'
import { usePolling } from '../../hooks/usePolling'
import { fetchLogs, fetchStatus } from '../../api/client'
import styles from './ModuleBackdrop.module.css'

const SLOTS = [
  { x: 14, y: 16 },
  { x: 34, y: 22 },
  { x: 54, y: 18 },
  { x: 74, y: 24 },
  { x: 86, y: 16 },
  { x: 22, y: 46 },
  { x: 44, y: 50 },
  { x: 66, y: 44 },
  { x: 84, y: 52 },
  { x: 28, y: 76 },
  { x: 50, y: 80 },
  { x: 72, y: 76 },
] as const

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

  const pulseIndex = useMemo(() => {
    if (modules.length === 0) return -1
    return Math.floor(Date.now() / 2500) % modules.length
  }, [modules.length, logs, data])

  return (
    <div className={styles.root} aria-hidden>
      <svg className={styles.links} viewBox="0 0 100 100" preserveAspectRatio="none">
        {modules.map((_, idx) => {
          if (idx >= modules.length - 1 || idx >= SLOTS.length - 1) return null
          const from = SLOTS[idx]
          const to = SLOTS[idx + 1]
          const fromActive = idx === pulseIndex || activeModuleNames.has(String(modules[idx]).toLowerCase())
          const toActive = idx + 1 === pulseIndex || activeModuleNames.has(String(modules[idx + 1]).toLowerCase())
          const cls = fromActive || toActive ? styles.linkActive : styles.linkIdle
          return <line key={`link-${idx}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={cls} />
        })}
      </svg>

      {modules.map((name, idx) => {
        const isActive = activeModuleNames.has(name.toLowerCase()) || idx === pulseIndex
        const statusClass = isActive ? styles.active : styles.idle
        const slot = SLOTS[idx % SLOTS.length]
        const delay = `${(idx % 7) * 0.35}s`
        return (
          <div
            key={`${name}-${idx}`}
            className={`${styles.node} ${statusClass}`}
            style={{ left: `${slot.x}%`, top: `${slot.y}%`, animationDelay: delay }}
            title={name}
          >
            <span className={styles.label}>{name}</span>
          </div>
        )
      })}
    </div>
  )
}
