import { useEffect, useMemo, useState } from 'react'
import { fetchConfig, sendChat } from '../api/client'
import styles from './ChatView.module.css'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

const CHAT_STORAGE_KEY = 'titanshift-chat-history-v1'

function loadSavedMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as ChatMessage[]
    if (!Array.isArray(parsed)) return []
    return parsed.filter((m) => typeof m?.text === 'string' && (m?.role === 'user' || m?.role === 'assistant'))
  } catch {
    return []
  }
}

export function ChatView() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>(loadSavedMessages)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preferredBackend, setPreferredBackend] = useState<string | null>(null)

  const canSend = useMemo(() => input.trim().length > 0 && !sending, [input, sending])

  useEffect(() => {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages.slice(-100)))
  }, [messages])

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

  async function send() {
    const text = input.trim()
    if (!text || sending) return

    setMessages((prev) => [...prev, { role: 'user', text }])
    setInput('')
    setSending(true)
    setError(null)

    try {
      const result = await sendChat({
        prompt: text,
        ...(preferredBackend ? { model_backend: preferredBackend } : {}),
      })
      const reply = (result.response ?? '').trim() || 'No response returned.'
      setMessages((prev) => [...prev, { role: 'assistant', text: reply }])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: 'Request failed. Check Health and provider settings, then try again.' },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={styles.root}>
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
                <p className={styles.msgRole}>{m.role === 'user' ? 'You' : 'TitanShift'}</p>
                <p className={styles.msgText}>{m.text}</p>
              </div>
            ))}
          </div>
        )}
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
