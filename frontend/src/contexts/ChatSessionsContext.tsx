import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useWorkspace } from './WorkspaceContext'

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  timestamp?: string
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
const MAX_SESSIONS_PER_WORKSPACE = 40

interface WorkspaceChatState {
  sessions: ChatSession[]
  currentSessionId: string
}

interface ChatStoreState {
  byWorkspace: Record<string, WorkspaceChatState>
}

function normalizeWorkspaceScopeKey(workspaceId: string, workspacePath?: string | null): string {
  const path = (workspacePath ?? '').trim()
  if (path) {
    return `path:${path.replace(/\\/g, '/').toLowerCase()}`
  }
  return `id:${workspaceId}`
}

function findFallbackWorkspaceState(
  byWorkspace: Record<string, WorkspaceChatState>,
  workspaceId: string,
): WorkspaceChatState | null {
  const direct = byWorkspace[`id:${workspaceId}`] ?? byWorkspace[workspaceId]
  if (direct) {
    return direct
  }
  if (byWorkspace.default) {
    return byWorkspace.default
  }

  const candidates = Object.entries(byWorkspace)
    .filter(([key]) => key.startsWith('path:') || key.startsWith('id:'))
    .map(([, state]) => state)
    .filter((state) => Array.isArray(state.sessions) && state.sessions.length > 0)

  if (candidates.length === 0) {
    return null
  }

  // Prefer the richest existing session bucket when workspace keys drift.
  return candidates.sort((a, b) => b.sessions.length - a.sessions.length)[0]
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

function pruneSessions(sessions: ChatSession[], keepSessionId?: string): ChatSession[] {
  const sorted = [...sessions].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  if (sorted.length <= MAX_SESSIONS_PER_WORKSPACE) {
    return sorted
  }

  const kept: ChatSession[] = []
  let preservedKeep = false
  for (const session of sorted) {
    if (kept.length < MAX_SESSIONS_PER_WORKSPACE) {
      kept.push(session)
      if (keepSessionId && session.id === keepSessionId) {
        preservedKeep = true
      }
      continue
    }
    if (keepSessionId && !preservedKeep && session.id === keepSessionId) {
      kept[kept.length - 1] = session
      preservedKeep = true
      break
    }
  }

  return kept.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
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
          byWorkspace[workspaceId] = {
            sessions: pruneSessions(sessions, currentSessionId),
            currentSessionId,
          }
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
      return {
        byWorkspace: {
          default: {
            sessions: pruneSessions(sessions, currentSessionId),
            currentSessionId,
          },
        },
      }
    }
  } catch {
    // ignore invalid persisted state
  }

  return { byWorkspace: { default: createWorkspaceState() } }
}

const defaultState = loadInitialState()

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
  const { currentWorkspaceId, currentWorkspacePath } = useWorkspace()
  const [store, setStore] = useState(loadInitialState)
  const workspaceScopeKey = useMemo(
    () => normalizeWorkspaceScopeKey(currentWorkspaceId, currentWorkspacePath),
    [currentWorkspaceId, currentWorkspacePath],
  )

  const active = useMemo(() => {
    const scoped = store.byWorkspace[workspaceScopeKey]
    if (scoped) return scoped
    return findFallbackWorkspaceState(store.byWorkspace, currentWorkspaceId) ?? createWorkspaceState()
  }, [store, workspaceScopeKey, currentWorkspaceId])
  const sessions = active.sessions
  const currentSessionId = active.currentSessionId

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  }, [store])

  useEffect(() => {
    setStore((prev) => {
      if (prev.byWorkspace[workspaceScopeKey]) return prev
      const fallback = findFallbackWorkspaceState(prev.byWorkspace, currentWorkspaceId)
      if (fallback) {
        return {
          byWorkspace: {
            ...prev.byWorkspace,
            [workspaceScopeKey]: fallback,
          },
        }
      }
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: createWorkspaceState(),
        },
      }
    })
  }, [workspaceScopeKey, currentWorkspaceId])

  const currentSession = useMemo(() => {
    return sessions.find((session) => session.id === currentSessionId) ?? sessions[0]
  }, [sessions, currentSessionId])

  function createSession() {
    const next = makeSession()
    setStore((prev) => {
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
            sessions: pruneSessions([next, ...state.sessions], next.id),
            currentSessionId: next.id,
          },
        },
      }
    })
  }

  function selectSession(id: string) {
    setStore((prev) => {
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
            sessions: state.sessions,
            currentSessionId: state.sessions.some((s) => s.id === id) ? id : state.currentSessionId,
          },
        },
      }
    })
  }

  function appendMessage(message: ChatMessage) {
    const stamped: ChatMessage = { ...message, timestamp: message.timestamp ?? new Date().toISOString() }
    setStore((prev) => {
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      const updated = state.sessions.map((session) => {
        if (session.id !== state.currentSessionId) return session
        const messages = [...session.messages, stamped]
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
          [workspaceScopeKey]: {
            currentSessionId: state.currentSessionId,
            sessions: pruneSessions(updated, state.currentSessionId),
          },
        },
      }
    })
  }

  function renameSession(id: string, title: string) {
    const nextTitle = title.trim()
    if (!nextTitle) return
    setStore((prev) => {
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
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
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      const sessions = state.sessions.map((session) => (
        session.id === id ? { ...session, archived: true, updatedAt: new Date().toISOString() } : session
      ))
      const activeSessions = sessions.filter((session) => !session.archived)
      const fallback = activeSessions[0] ?? makeSession()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
            currentSessionId: state.currentSessionId === id ? fallback.id : state.currentSessionId,
            sessions: activeSessions.length > 0 ? sessions.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)) : [fallback, ...sessions],
          },
        },
      }
    })
  }

  function restoreSession(id: string) {
    setStore((prev) => {
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
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
      const state = prev.byWorkspace[workspaceScopeKey] ?? prev.byWorkspace[currentWorkspaceId] ?? createWorkspaceState()
      const remaining = state.sessions.filter((session) => session.id !== id)
      if (remaining.length === 0) {
        const next = makeSession()
        return {
          byWorkspace: {
            ...prev.byWorkspace,
            [workspaceScopeKey]: { sessions: [next], currentSessionId: next.id },
          },
        }
      }
      return {
        byWorkspace: {
          ...prev.byWorkspace,
          [workspaceScopeKey]: {
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