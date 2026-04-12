import styles from './StatusIndicator.module.css'

const STATUSES = ['Thinking...', 'Processing...', 'Researching...', 'Analyzing...', 'Reasoning...']

interface StatusIndicatorProps {
  isActive: boolean
}

export function StatusIndicator({ isActive }: StatusIndicatorProps) {
  if (!isActive) return null

  return (
    <div className={styles.root} aria-live="polite">
      <div className={styles.spinner} />
      <span className={styles.text}>{STATUSES[Math.floor(Math.random() * STATUSES.length)]}</span>
    </div>
  )
}
