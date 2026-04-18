import { useState } from 'react'
import { DiffViewer } from './DiffViewer'
import styles from './PreviewPanel.module.css'

interface PreviewPanelProps {
  /** List of patch summaries from task output */
  patchSummaries?: string[]
  /** List of updated paths from task output */
  updatedPaths?: string[]
  /** Diff text to show (optional; pass raw unified diff) */
  diff?: string
  /** Called when user submits a follow-up feedback prompt */
  onFeedback?: (feedbackPrompt: string) => void
  /** Whether a follow-up request is in flight */
  feedbackLoading?: boolean
}

export function PreviewPanel({ patchSummaries = [], updatedPaths = [], diff, onFeedback, feedbackLoading }: PreviewPanelProps) {
  const [feedbackText, setFeedbackText] = useState('')
  const [diffOpen, setDiffOpen] = useState(true)

  const hasContent = patchSummaries.length > 0 || updatedPaths.length > 0 || !!diff

  if (!hasContent) return null

  function submitFeedback() {
    const text = feedbackText.trim()
    if (!text || feedbackLoading) return
    onFeedback?.(text)
    setFeedbackText('')
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className={styles.title}>Output Preview</span>
        <span className={styles.count}>{updatedPaths.length + patchSummaries.length} change(s)</span>
      </div>

      {patchSummaries.length > 0 && (
        <ul className={styles.summaryList}>
          {patchSummaries.map((s, i) => (
            <li key={i} className={styles.summaryItem}>
              <span className={styles.summaryIcon}>✦</span>
              {s}
            </li>
          ))}
        </ul>
      )}

      {updatedPaths.length > 0 && (
        <div className={styles.pathGroup}>
          <span className={styles.pathLabel}>Files modified</span>
          <ul className={styles.pathList}>
            {updatedPaths.map((p, i) => (
              <li key={i} className={styles.pathItem}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {diff && (
        <div className={styles.diffSection}>
          <button
            className={styles.diffToggle}
            onClick={() => setDiffOpen((v) => !v)}
          >
            {diffOpen ? '▾' : '▸'} Diff
          </button>
          {diffOpen && <DiffViewer diff={diff} />}
        </div>
      )}

      {onFeedback && (
        <div className={styles.feedbackRow}>
          <textarea
            className={styles.feedbackInput}
            placeholder="Request a change or iteration on this output…"
            rows={2}
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            disabled={feedbackLoading}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submitFeedback()
              }
            }}
          />
          <button
            className={styles.feedbackBtn}
            onClick={submitFeedback}
            disabled={!feedbackText.trim() || feedbackLoading}
          >
            {feedbackLoading ? '…' : 'Iterate'}
          </button>
        </div>
      )}
    </div>
  )
}
