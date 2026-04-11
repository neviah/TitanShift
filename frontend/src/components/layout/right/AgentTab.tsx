import styles from './AgentTab.module.css'

export function AgentTab() {
  return (
    <div className={styles.root}>
      <section className={styles.section}>
        <h3 className={styles.heading}>Active Agent</h3>
        <div className={styles.card}>
          <div className={styles.row}>
            <span className={styles.label}>Name</span>
            <span className={styles.value}>orchestrator</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Status</span>
            <span className="badge badge-ok">idle</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Model</span>
            <span className={`${styles.value} font-mono`}>—</span>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Budget</h3>
        <div className={styles.card}>
          <div className={styles.row}>
            <span className={styles.label}>Steps</span>
            <span className={styles.value}>—</span>
          </div>
          <div className={styles.row}>
            <span className={styles.label}>Tokens</span>
            <span className={styles.value}>—</span>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Last Action</h3>
        <p className={styles.empty}>No activity yet</p>
      </section>
    </div>
  )
}
