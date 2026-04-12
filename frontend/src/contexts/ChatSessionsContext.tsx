import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  updatedAt: string
}

interface ChatSessionsContextValue {
  sessions: ChatSession[]
  currentSessionId: string
  currentSession: ChatSession
  createSession: () => void
  selectSession: (id: string) => void
  appendMessage: (message: ChatMessage) => void
}

const STORAGE_KEY = 'titanshift-chat-sessions-v1'

function makeSession(partial?: Partial<ChatSession>): ChatSession {
  const now = new Date().toISOString()
  return {
    id: partial?.id ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: partial?.title ?? 'New Chat',
    messages: partial?.messages ?? [],
    updatedAt: partial?.updatedAt ?? now,
  }
}

function loadInitialState(): { sessions: ChatSession[]; currentSessionId: string } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { sessions?: ChatSession[]; currentSessionId?: string }
      const sessions = Array.isArray(parsed?.sessions) && parsed.sessions.length > 0
        ? parsed.sessions.map((session) => makeSession(session))
        : [makeSession()]
      const currentSessionId = sessions.some((s) => s.id === parsed?.currentSessionId)
        ? String(parsed?.currentSessionId)
        : sessions[0].id
      return { sessions, currentSessionId }
    }
  } catch {
    // ignore invalid persisted state
  }

  const initial = makeSession()
  return { sessions: [initial], currentSessionId: initial.id }
}

const defaultState = loadInitialState()

const ChatSessionsContext = createContext<ChatSessionsContextValue>({
  sessions: defaultState.sessions,
  currentSessionId: defaultState.currentSessionId,
  currentSession: defaultState.sessions[0],
  createSession: () => {},
  selectSession: () => {},
  appendMessage: () => {},
})

export function ChatSessionsProvider({ children }: { children: ReactNode }) {
  const [{ sessions, currentSessionId }, setState] = useState(loadInitialState)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ sessions, currentSessionId }))
  }, [sessions, currentSessionId])

  const currentSession = useMemo(() => {
    return sessions.find((session) => session.id === currentSessionId) ?? sessions[0]
  }, [sessions, currentSessionId])

  function createSession() {
    const next = makeSession()
    setState((prev) => ({
      sessions: [next, ...prev.sessions],
      currentSessionId: next.id,
    }))
  }

  function selectSession(id: string) {
    setState((prev) => ({
      sessions: prev.sessions,
      currentSessionId: prev.sessions.some((s) => s.id === id) ? id : prev.currentSessionId,
    }))
  }

  function appendMessage(message: ChatMessage) {
    setState((prev) => ({
      currentSessionId: prev.currentSessionId,
      sessions: prev.sessions.map((session) => {
        if (session.id !== prev.currentSessionId) return session
        const messages = [...session.messages, message]
        const title = session.title === 'New Chat' && message.role === 'user'
          ? message.text.trim().slice(0, 36) || 'New Chat'
          : session.title
        return {
          ...session,
          title,
          messages,
          updatedAt: new Date().toISOString(),
        }
      }).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    }))
  }

  return (
    <ChatSessionsContext.Provider value={{ sessions, currentSessionId, currentSession, createSession, selectSession, appendMessage }}>
      {children}
    </ChatSessionsContext.Provider>
  )
}

export function useChatSessions() {
  return useContext(ChatSessionsContext)
}