import styles from './ChatView.module.css'

export function ChatView() {
  return (
    <div className={styles.root}>
      <div className={styles.messages}>
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>TitanShift</p>
          <p className={styles.emptyHint}>Start a conversation…</p>
        </div>
      </div>

      <div className={styles.inputRow}>
        <textarea
          className={styles.input}
          placeholder="Message…"
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
            }
          }}
        />
        <button className={styles.sendBtn} title="Send">
          ▶
        </button>
      </div>
    </div>
  )
}
