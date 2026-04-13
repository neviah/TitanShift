import styles from './HeartbeatTrail.module.css'

export function HeartbeatTrail() {
  return (
    <div className={styles.root} aria-hidden>
      <div className={styles.scan} />
      <div className={styles.wave} />
    </div>
  )
}
