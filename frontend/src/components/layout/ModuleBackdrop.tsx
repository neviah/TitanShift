import { useMemo } from 'react'
import { usePolling } from '../../hooks/usePolling'
import { fetchStatus } from '../../api/client'
import styles from './ModuleBackdrop.module.css'

export function ModuleBackdrop() {
  const { data } = usePolling(fetchStatus, { interval: 12000 })

  const modules = useMemo(() => {
    const fromHealth = (data?.health ?? []).map((h) => h.name)
    const loaded = data?.loaded_modules ?? []
    const merged = Array.from(new Set([...fromHealth, ...loaded]))
    return merged.slice(0, 18)
  }, [data])

  return (
    <div className={styles.root} aria-hidden>
      {modules.map((name, idx) => {
        const status = (data?.health ?? []).find((h) => h.name === name)?.status?.toLowerCase() ?? 'healthy'
        const statusClass = status.includes('healthy') || status.includes('ok') || status.includes('up')
          ? styles.healthy
          : status.includes('degraded') || status.includes('warn')
            ? styles.warn
            : styles.error
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
            <span className={styles.dot} />
            <span className={styles.label}>{name}</span>
          </div>
        )
      })}
    </div>
  )
}
