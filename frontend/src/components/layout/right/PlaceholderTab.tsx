import styles from './PlaceholderTab.module.css'

export function PlaceholderTab({ label }: { label: string }) {
  return (
    <div className={styles.root}>
      <p className={styles.text}>{label} — coming soon</p>
    </div>
  )
}
