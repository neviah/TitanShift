import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ChatMessage, ChatSession } from './ChatSessionsContext'

export interface TaskDraft {
  id: string
  title: string
  sourceSessionId: string
  steps: string[]
  createdAt: string
  lastExecutedAt?: string
  lastResult?: string
  execution?: {
    startedAt: string
    finishedAt?: string
    steps: Array<{
      instruction: string
      status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
      output?: string
    }>
  }
}

interface TaskDraftsContextValue {
  drafts: TaskDraft[]
  promoteSessionToDraft: (session: ChatSession) => TaskDraft | null
  promoteSelectionToDraft: (session: ChatSession, selectedMessageIndexes: number[]) => TaskDraft | null
  deleteDraft: (id: string) => void
  setExecutionResult: (id: string, result: string) => void
  setDraftTitle: (id: string, title: string) => void
  setDraftStep: (id: string, index: number, text: string) => void
  addDraftStep: (id: string) => void
  removeDraftStep: (id: string, index: number) => void
  moveDraftStep: (id: string, index: number, direction: -1 | 1) => void
  startExecution: (id: string, steps: string[]) => void
  resetExecutionFromStep: (id: string, index: number) => void
  updateExecutionStep: (id: string, index: number, status: 'pending' | 'running' | 'done' | 'error' | 'skipped', output?: string) => void
  finishExecution: (id: string) => void
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
  promoteSelectionToDraft: () => null,
  deleteDraft: () => {},
  setExecutionResult: () => {},
  setDraftTitle: () => {},
  setDraftStep: () => {},
  addDraftStep: () => {},
  removeDraftStep: () => {},
  moveDraftStep: () => {},
  startExecution: () => {},
  resetExecutionFromStep: () => {},
  updateExecutionStep: () => {},
  finishExecution: () => {},
})

function extractStepsFromTexts(texts: string[]): string[] {
  const userText = texts.join('\n').trim()
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

function extractStepsFromSession(session: ChatSession): string[] {
  return extractStepsFromTexts(
    session.messages
      .filter((m) => m.role === 'user')
      .map((m) => m.text),
  )
}

function extractStepsFromSelection(session: ChatSession, selectedMessageIndexes: number[]): string[] {
  if (selectedMessageIndexes.length === 0) return []

  const selectedIndexSet = new Set(selectedMessageIndexes)
  const selectedUserTexts = session.messages
    .map((m, index) => ({ m, index }))
    .filter((item): item is { m: ChatMessage; index: number } => item.m.role === 'user' && selectedIndexSet.has(item.index))
    .map((item) => item.m.text)

  return extractStepsFromTexts(selectedUserTexts)
}

export function TaskDraftsProvider({ children }: { children: ReactNode }) {
  const [drafts, setDrafts] = useState<TaskDraft[]>(loadInitial)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(drafts))
  }, [drafts])

  function createDraft(session: ChatSession, steps: string[], title: string): TaskDraft {
    return {
      id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title,
      sourceSessionId: session.id,
      steps,
      createdAt: new Date().toISOString(),
    }
  }

  function promoteSessionToDraft(session: ChatSession): TaskDraft | null {
    const steps = extractStepsFromSession(session)
    if (steps.length === 0) return null

    const draft = createDraft(session, steps, session.title || 'Promoted Task Draft')
    setDrafts((prev) => [draft, ...prev])
    return draft
  }

  function promoteSelectionToDraft(session: ChatSession, selectedMessageIndexes: number[]): TaskDraft | null {
    const steps = extractStepsFromSelection(session, selectedMessageIndexes)
    if (steps.length === 0) return null

    const baseTitle = session.title || 'Promoted Task Draft'
    const draft = createDraft(session, steps, `${baseTitle} (selection)`)
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

  function setDraftTitle(id: string, title: string) {
    const nextTitle = title.trim()
    if (!nextTitle) return
    setDrafts((prev) => prev.map((d) => (d.id === id ? { ...d, title: nextTitle } : d)))
  }

  function setDraftStep(id: string, index: number, text: string) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id) return d
      const next = d.steps.slice()
      if (index < 0 || index >= next.length) return d
      next[index] = text
      return { ...d, steps: next }
    }))
  }

  function addDraftStep(id: string) {
    setDrafts((prev) => prev.map((d) => (d.id === id ? { ...d, steps: [...d.steps, ''] } : d)))
  }

  function removeDraftStep(id: string, index: number) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id) return d
      return { ...d, steps: d.steps.filter((_, i) => i !== index) }
    }))
  }

  function moveDraftStep(id: string, index: number, direction: -1 | 1) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id) return d
      const nextIndex = index + direction
      if (index < 0 || nextIndex < 0 || nextIndex >= d.steps.length) return d
      const steps = d.steps.slice()
      const [item] = steps.splice(index, 1)
      steps.splice(nextIndex, 0, item)
      return { ...d, steps }
    }))
  }

  function startExecution(id: string, steps: string[]) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id) return d
      return {
        ...d,
        execution: {
          startedAt: new Date().toISOString(),
          steps: steps.map((instruction) => ({ instruction, status: 'pending' as const })),
        },
      }
    }))
  }

  function resetExecutionFromStep(id: string, index: number) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id || !d.execution) return d
      const steps = d.execution.steps.slice().map((step, i) => {
        if (i < index) return step
        return {
          ...step,
          status: 'pending' as const,
          output: undefined,
        }
      })
      return {
        ...d,
        execution: {
          ...d.execution,
          startedAt: new Date().toISOString(),
          finishedAt: undefined,
          steps,
        },
      }
    }))
  }

  function updateExecutionStep(id: string, index: number, status: 'pending' | 'running' | 'done' | 'error' | 'skipped', output?: string) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id || !d.execution) return d
      const steps = d.execution.steps.slice()
      if (index < 0 || index >= steps.length) return d
      steps[index] = {
        ...steps[index],
        status,
        ...(typeof output === 'string' ? { output } : {}),
      }
      return {
        ...d,
        execution: {
          ...d.execution,
          steps,
        },
      }
    }))
  }

  function finishExecution(id: string) {
    setDrafts((prev) => prev.map((d) => {
      if (d.id !== id || !d.execution) return d
      return {
        ...d,
        lastExecutedAt: new Date().toISOString(),
        execution: {
          ...d.execution,
          finishedAt: new Date().toISOString(),
        },
      }
    }))
  }

  const value = useMemo(
    () => ({
      drafts,
      promoteSessionToDraft,
      promoteSelectionToDraft,
      deleteDraft,
      setExecutionResult,
      setDraftTitle,
      setDraftStep,
      addDraftStep,
      removeDraftStep,
      moveDraftStep,
      startExecution,
      resetExecutionFromStep,
      updateExecutionStep,
      finishExecution,
    }),
    [drafts],
  )

  return <TaskDraftsContext.Provider value={value}>{children}</TaskDraftsContext.Provider>
}

export function useTaskDrafts() {
  return useContext(TaskDraftsContext)
}