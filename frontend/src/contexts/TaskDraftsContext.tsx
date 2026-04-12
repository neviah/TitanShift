import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ChatSession } from './ChatSessionsContext'

export interface TaskDraft {
  id: string
  title: string
  sourceSessionId: string
  steps: string[]
  createdAt: string
  lastExecutedAt?: string
  lastResult?: string
}

interface TaskDraftsContextValue {
  drafts: TaskDraft[]
  promoteSessionToDraft: (session: ChatSession) => TaskDraft | null
  deleteDraft: (id: string) => void
  setExecutionResult: (id: string, result: string) => void
}

const STORAGE_KEY = 'titanshift-task-drafts-v1'

function loadInitial(): TaskDraft[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as TaskDraft[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const TaskDraftsContext = createContext<TaskDraftsContextValue>({
  drafts: [],
  promoteSessionToDraft: () => null,
  deleteDraft: () => {},
  setExecutionResult: () => {},
})

function extractStepsFromSession(session: ChatSession): string[] {
  const userText = session.messages
    .filter((m) => m.role === 'user')
    .map((m) => m.text)
    .join('\n')
    .trim()

  if (!userText) return []

  const lines = userText
    .split(/\r?\n|(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 8)

  const deduped: string[] = []
  for (const line of lines) {
    if (!deduped.includes(line)) deduped.push(line)
  }

  return deduped.slice(0, 20)
}

export function TaskDraftsProvider({ children }: { children: ReactNode }) {
  const [drafts, setDrafts] = useState<TaskDraft[]>(loadInitial)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(drafts))
  }, [drafts])

  function promoteSessionToDraft(session: ChatSession): TaskDraft | null {
    const steps = extractStepsFromSession(session)
    if (steps.length === 0) return null

    const draft: TaskDraft = {
      id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title: session.title || 'Promoted Task Draft',
      sourceSessionId: session.id,
      steps,
      createdAt: new Date().toISOString(),
    }

    setDrafts((prev) => [draft, ...prev])
    return draft
  }

  function deleteDraft(id: string) {
    setDrafts((prev) => prev.filter((d) => d.id !== id))
  }

  function setExecutionResult(id: string, result: string) {
    setDrafts((prev) => prev.map((d) => (
      d.id === id
        ? { ...d, lastExecutedAt: new Date().toISOString(), lastResult: result }
        : d
    )))
  }

  const value = useMemo(
    () => ({ drafts, promoteSessionToDraft, deleteDraft, setExecutionResult }),
    [drafts],
  )

  return <TaskDraftsContext.Provider value={value}>{children}</TaskDraftsContext.Provider>
}

export function useTaskDrafts() {
  return useContext(TaskDraftsContext)
}