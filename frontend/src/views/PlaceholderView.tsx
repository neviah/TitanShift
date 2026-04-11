import styles from './PlaceholderView.module.css'

export function PlaceholderView({ label }: { label: string }) {
  return (
    <div className={styles.root}>
      <p className={styles.label}>{label}</p>
      <p className={styles.hint}>Coming soon</p>
    </div>
  )
}
