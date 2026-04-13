import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useWorkspace } from './WorkspaceContext'

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  updatedAt: string
  archived?: boolean
}

interface ChatSessionsContextValue {
  sessions: ChatSession[]
  currentSessionId: string
  currentSession: ChatSession
  createSession: () => void
  selectSession: (id: string) => void
  appendMessage: (message: ChatMessage) => void
  renameSession: (id: string, title: string) => void
  archiveSession: (id: string) => void
  restoreSession: (id: string) => void
  deleteSession: (id: string) => void
}

const STORAGE_KEY = 'titanshift-chat-sessions-v1'

interface WorkspaceChatState {
  sessions: ChatSession[]
  currentSessionId: string
}

interface ChatStoreState {
  byWorkspace: Record<string, WorkspaceChatState>
}

function makeSession(partial?: Partial<ChatSession>): ChatSession {
  const now = new Date().toISOString()
  return {
    id: partial?.id ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: partial?.title ?? 'New Chat',
    messages: partial?.messages ?? [],
    updatedAt: partial?.updatedAt ?? now,
    archived: partial?.archived ?? false,
  }
}

function createWorkspaceState(): WorkspaceChatState {
  const initial = makeSession()
  return { sessions: [initial], currentSessionId: initial.id }
}

function loadInitialState(): ChatStoreState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as
        | { byWorkspace?: Record<string, WorkspaceChatState> }
        | { sessions?: ChatSession[]; currentSessionId?: string }

      if ('byWorkspace' in parsed && parsed.byWorkspace && typeof parsed.byWorkspace === 'object') {
        const byWorkspace: Record<string, WorkspaceChatState> = {}
        for (const [workspaceId, state] of Object.entries(parsed.byWorkspace)) {
          const sessions = Array.isArray(state?.sessions) && state.sessions.length > 0
            ? state.sessions.map((session) => makeSession(session))
            : [makeSession()]
          const currentSessionId = sessions.some((s) => s.id === state?.currentSessionId)
            ? String(state.currentSessionId)
            : sessions[0].id
          byWorkspace[workspaceId] = { sessions, currentSessionId }
        }
        if (Object.keys(byWorkspace).length > 0) {
          return { byWorkspace }
        }
      }

      const legacy = parsed as { sessions?: ChatSession[]; currentSessionId?: string }
      const sessions = Array.isArray(legacy?.sessions) && legacy.sessions.length > 0
        ? legacy.sessions.map((session) => makeSession(session))
        : [makeSession()]
      const currentSessionId = sessions.some((s) => s.id === legacy?.currentSessionId)
        ? String(legacy?.currentSessionId)
        : sessions[0].id
      return { byWorkspace: { default: { sessions, currentSessionId } } }
    }
  } catch {
    // ignore invalid persisted state
  }

  return { byWorkspace: { default: createWorkspaceState() } }
}

const defaultState = loadInitialState()

function activeWorkspaceState(store: ChatStoreState, workspaceId: string): WorkspaceChatState {
  return store.byWorkspace[workspaceId] ?? createWorkspaceState()
}

const ChatSessionsContext = createContext<ChatSessionsContextValue>({
  sessions: defaultState.byWorkspace.default?.sessions ?? [makeSession()],
  currentSessionId: defaultState.byWorkspace.default?.currentSessionId ?? 'default',
  currentSession: defaultState.byWorkspace.default?.sessions?.[0] ?? makeSession(),
  createSession: () => {},
  selectSession: () => {},
  appendMessage: () => {},
  renameSession: () => {},
  archiveSession: () => {},
  restoreSession: () => {},
  deleteSession: () => {},
})

export function ChatSessionsProvider({ children }: { children: ReactNode }) {
  const { currentWorkspaceId } = useWorkspace()
  const [store, setStore] = useState(loadInitialState)

  const active = useMemo(
    () => activeWorkspaceState(store, currentWorkspaceId),
    [store, currentWorkspaceId],
  )
  const sessions = active.sessions
  const currentSessionId = active.currentSessionId

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  }, [store])

  useEffect(() => {
    setStore((prev) => {
      if (prev.byWorkspace[currentWorkspaceId]) return prev
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: createWorkspaceState(),
        },
      }
    })
  }, [currentWorkspaceId])

  const currentSession = useMemo(() => {
    return sessions.find((session) => session.id === currentSessionId) ?? sessions[0]
  }, [sessions, currentSessionId])

  function createSession() {
    const next = makeSession()
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            sessions: [next, ...state.sessions],
            currentSessionId: next.id,
          },
        },
      }
    })
  }

  function selectSession(id: string) {
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            sessions: state.sessions,
            currentSessionId: state.sessions.some((s) => s.id === id) ? id : state.currentSessionId,
          },
        },
      }
    })
  }

  function appendMessage(message: ChatMessage) {
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      const updated = state.sessions.map((session) => {
        if (session.id !== state.currentSessionId) return session
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
      }).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))

      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            currentSessionId: state.currentSessionId,
            sessions: updated,
          },
        },
      }
    })
  }

  function renameSession(id: string, title: string) {
    const nextTitle = title.trim()
    if (!nextTitle) return
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            currentSessionId: state.currentSessionId,
            sessions: state.sessions.map((session) => (
              session.id === id ? { ...session, title: nextTitle, updatedAt: new Date().toISOString() } : session
            )).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
          },
        },
      }
    })
  }

  function archiveSession(id: string) {
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      const sessions = state.sessions.map((session) => (
        session.id === id ? { ...session, archived: true, updatedAt: new Date().toISOString() } : session
      ))
      const activeSessions = sessions.filter((session) => !session.archived)
      const fallback = activeSessions[0] ?? makeSession()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            currentSessionId: state.currentSessionId === id ? fallback.id : state.currentSessionId,
            sessions: activeSessions.length > 0 ? sessions.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)) : [fallback, ...sessions],
          },
        },
      }
    })
  }

  function restoreSession(id: string) {
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            currentSessionId: id,
            sessions: state.sessions.map((session) => (
              session.id === id ? { ...session, archived: false, updatedAt: new Date().toISOString() } : session
            )).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
          },
        },
      }
    })
  }

  function deleteSession(id: string) {
    setStore((prev) => {
      const state = activeWorkspaceState(prev, currentWorkspaceId)
      const remaining = state.sessions.filter((session) => session.id !== id)
      if (remaining.length === 0) {
        const next = makeSession()
        return {
          byWorkspace: {
            ...prev.byWorkspace,
            [currentWorkspaceId]: { sessions: [next], currentSessionId: next.id },
          },
        }
      }
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [currentWorkspaceId]: {
            sessions: remaining,
            currentSessionId: state.currentSessionId === id ? remaining[0].id : state.currentSessionId,
          },
        },
      }
    })
  }

  return (
    <ChatSessionsContext.Provider value={{ sessions, currentSessionId, currentSession, createSession, selectSession, appendMessage, renameSession, archiveSession, restoreSession, deleteSession }}>
      {children}
    </ChatSessionsContext.Provider>
  )
}

export function useChatSessions() {
  return useContext(ChatSessionsContext)
}