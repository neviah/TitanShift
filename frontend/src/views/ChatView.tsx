import { useEffect, useMemo, useState } from 'react'
import { fetchConfig, sendChat } from '../api/client'
import { useChatSessions } from '../contexts/ChatSessionsContext'
import { useTaskDrafts } from '../contexts/TaskDraftsContext'
import styles from './ChatView.module.css'

export function ChatView() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [promoteMsg, setPromoteMsg] = useState<string | null>(null)
  const [preferredBackend, setPreferredBackend] = useState<string | null>(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedMessageIndexes, setSelectedMessageIndexes] = useState<number[]>([])
  const { currentSession, appendMessage } = useChatSessions()
  const { promoteSessionToDraft, promoteSelectionToDraft } = useTaskDrafts()

  const messages = currentSession.messages

  const taskCandidate = useMemo(() => {
    const userMessages = messages.filter((m) => m.role === 'user')
    const totalChars = userMessages.reduce((sum, m) => sum + m.text.length, 0)
    return userMessages.length >= 4 || totalChars >= 500
  }, [messages])

  const canSend = useMemo(() => input.trim().length > 0 && !sending, [input, sending])

  useEffect(() => {
    let mounted = true
    void fetchConfig()
      .then((cfg) => {
        if (!mounted) return
        const backend = cfg['model.default_backend']
        if (typeof backend === 'string' && backend.trim().length > 0) {
          setPreferredBackend(backend)
        }
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    setError(null)
    setInput('')
    setSelectionMode(false)
    setSelectedMessageIndexes([])
  }, [currentSession.id])

  async function send() {
    const text = input.trim()
    if (!text || sending) return

    appendMessage({ role: 'user', text })
    setInput('')
    setSending(true)
    setError(null)

    try {
      const result = await sendChat({
        prompt: text,
        ...(preferredBackend ? { model_backend: preferredBackend } : {}),
      })
      const reply = (result.response ?? '').trim() || 'No response returned.'
      appendMessage({ role: 'assistant', text: reply })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      appendMessage({ role: 'assistant', text: 'Request failed. Check Health and provider settings, then try again.' })
    } finally {
      setSending(false)
    }
  }

  function promoteCurrentSession() {
    const draft = promoteSessionToDraft(currentSession)
    if (draft) {
      setPromoteMsg(`Draft created: ${draft.title}`)
    } else {
      setPromoteMsg('Not enough user instructions to generate a task draft yet.')
    }
  }

  function toggleSelectedMessage(index: number) {
    setSelectedMessageIndexes((prev) => (
      prev.includes(index) ? prev.filter((value) => value !== index) : [...prev, index]
    ))
  }

  function promoteSelectedMessages() {
    const draft = promoteSelectionToDraft(currentSession, selectedMessageIndexes)
    if (draft) {
      setPromoteMsg(`Draft created from selection: ${draft.title}`)
      setSelectionMode(false)
      setSelectedMessageIndexes([])
    } else {
      setPromoteMsg('Select one or more user messages with instruction-like content first.')
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.topBar}>
        <div className={styles.topActions}>
          <button className={styles.promoteBtn} onClick={promoteCurrentSession}>Promote To Task</button>
          <button
            className={`${styles.promoteBtn} ${selectionMode ? styles.promoteBtnActive : ''}`}
            onClick={() => {
              setSelectionMode((prev) => !prev)
              setSelectedMessageIndexes([])
            }}
          >
            {selectionMode ? 'Cancel Selection' : 'Select Messages'}
          </button>
          {selectionMode && (
            <button
              className={styles.promoteBtn}
              onClick={promoteSelectedMessages}
              disabled={selectedMessageIndexes.length === 0}
            >
              Promote Selected ({selectedMessageIndexes.length})
            </button>
          )}
        </div>
        {taskCandidate && <span className={styles.candidateHint}>Complex thread detected: good task candidate</span>}
      </div>

      <div className={styles.messages}>
        {messages.length === 0 ? (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>TitanShift</p>
            <p className={styles.emptyHint}>Start a conversation...</p>
          </div>
        ) : (
          <div className={styles.thread}>
            {messages.map((m, i) => (
              <div key={`${m.role}-${i}`} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.assistant}`}>
                <div className={styles.msgHead}>
                  <p className={styles.msgRole}>{m.role === 'user' ? 'You' : 'TitanShift'}</p>
                  {selectionMode && m.role === 'user' && (
                    <label className={styles.selectLabel}>
                      <input
                        type="checkbox"
                        checked={selectedMessageIndexes.includes(i)}
                        onChange={() => toggleSelectedMessage(i)}
                      />
                      Select
                    </label>
                  )}
                </div>
                <p className={styles.msgText}>{m.text}</p>
              </div>
            ))}
          </div>
        )}
        {promoteMsg && <p className={`${styles.error} text-info`}>{promoteMsg}</p>}
        {error && <p className={`${styles.error} text-error`}>{error}</p>}
      </div>

      <div className={styles.inputRow}>
        <textarea
          className={styles.input}
          placeholder="Message..."
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
        />
        <button className={styles.sendBtn} title="Send" onClick={() => void send()} disabled={!canSend}>
          {sending ? '...' : '▶'}
        </button>
      </div>
    </div>
  )
}
