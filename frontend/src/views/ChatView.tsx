import { useState } from 'react'
import styles from './ChatView.module.css'

export function ChatView() {
  const [input, setInput] = useState('')

  function send() {
    const text = input.trim()
    if (!text) return
    // TODO: dispatch to backend chat endpoint
    setInput('')
  }

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
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        <button className={styles.sendBtn} title="Send" onClick={send}>
          ▶
        </button>
      </div>
    </div>
  )
}
