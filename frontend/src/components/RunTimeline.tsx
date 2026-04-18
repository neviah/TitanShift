import type { StreamEvent } from '../hooks/useTaskStream'
import styles from './RunTimeline.module.css'

interface RunTimelineProps {
  events: StreamEvent[]
  status: 'idle' | 'connecting' | 'streaming' | 'done' | 'error'
}

function eventLabel(event: StreamEvent): string {
  switch (event.type) {
    case 'start':
      return `Task started (max ${event.max_steps as number} steps, ${event.max_tokens as number} tokens)`
    case 'step': {
      const calls = event.tool_calls as Array<{ tool: string }> | undefined
      if (calls && calls.length > 0) {
        return `Step ${event.step as number}: calling ${calls.map((c) => c.tool).join(', ')}`
      }
      return `Step ${event.step as number}`
    }
    case 'tool_result': {
      const ok = event.ok !== false
      return `${ok ? '✓' : '✗'} ${event.tool as string}`
    }
    case 'text_delta':
      return 'Model response received'
    case 'done':
      return (event.success as boolean) ? '✓ Done' : '✗ Done (failed)'
    case 'artifact_emit':
      return `⬡ Artifact: ${(event.title as string) || (event.artifact_id as string) || 'generated'}`
    case 'error':
      return `Error: ${event.message as string}`
    default:
      return event.type
  }
}

function eventKind(type: string): string {
  if (type === 'error') return styles.kindError
  if (type === 'done') return styles.kindDone
  if (type === 'tool_result') return styles.kindTool
  if (type === 'step') return styles.kindStep
  if (type === 'text_delta') return styles.kindText
  if (type === 'artifact_emit') return styles.kindArtifact
  return styles.kindInfo
}

export function RunTimeline({ events, status }: RunTimelineProps) {
  if (status === 'idle') return null

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className={styles.title}>Run Timeline</span>
        <span className={`${styles.statusBadge} ${styles[`status_${status}`]}`}>{status}</span>
      </div>
      <ol className={styles.list}>
        {events
          .filter((e) => e.type !== 'eof')
          .map((event, i) => (
            <li key={i} className={`${styles.item} ${eventKind(event.type)}`}>
              <span className={styles.dot} />
              <span className={styles.label}>{eventLabel(event)}</span>
              {event.type === 'step' && Array.isArray(event.tool_calls) && (
                <ul className={styles.argList}>
                  {(event.tool_calls as Array<{ tool: string; args: unknown }>).map((tc, j) => (
                    <li key={j} className={styles.argItem}>
                      <code className={styles.toolName}>{tc.tool}</code>
                      {(() => {
                        if (!tc.args || typeof tc.args !== 'object' || Array.isArray(tc.args)) return null
                        const argKeys = Object.keys(tc.args as Record<string, unknown>)
                        if (argKeys.length === 0) return null
                        return (
                          <span className={styles.argHint}>
                            {argKeys.slice(0, 3).join(', ')}
                          </span>
                        )
                      })()}
                    </li>
                  ))}
                </ul>
              )}
              {event.type === 'tool_result' && typeof event.summary === 'string' && (
                <p className={styles.summary}>{String(event.summary).slice(0, 120)}</p>
              )}
              {event.type === 'artifact_emit' && typeof event.mime_type === 'string' && event.mime_type && (
                <p className={styles.summary}>{event.mime_type}</p>
              )}
              {event.type === 'done' && Array.isArray(event.patch_summaries) && (event.patch_summaries as string[]).length > 0 && (
                <ul className={styles.argList}>
                  {(event.patch_summaries as string[]).map((s, j) => (
                    <li key={j} className={styles.argItem}>{s}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        {status === 'streaming' && (
          <li className={`${styles.item} ${styles.kindInfo}`}>
            <span className={`${styles.dot} ${styles.dotPulse}`} />
            <span className={styles.label}>Running…</span>
          </li>
        )}
      </ol>
    </div>
  )
}
