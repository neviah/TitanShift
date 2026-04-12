import { useMemo } from 'react'
import styles from './StatusIndicator.module.css'

const STATUSES = ['Thinking...', 'Processing...', 'Researching...', 'Analyzing...', 'Reasoning...']

interface StatusIndicatorProps {
  isActive: boolean
}

export function StatusIndicator({ isActive }: StatusIndicatorProps) {
  const status = useMemo(() => {
    const elapsed = Math.floor(Date.now() / 1500)
    return STATUSES[elapsed % STATUSES.length]
  }, [isActive])

  if (!isActive) return null

  return (
    <div className={styles.root} aria-live="polite">
      <div className={styles.spinner} />
      <span className={styles.text}>{status}</span>
    </div>
  )
}
