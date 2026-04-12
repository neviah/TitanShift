import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

interface Workspace {
  id: string
  name: string
  path?: string
  source: 'manual' | 'folder'
}

interface WorkspaceContextValue {
  workspaces: Workspace[]
  currentWorkspaceId: string
  currentWorkspaceName: string
  currentWorkspacePath: string | null
  selectWorkspace: (id: string) => void
  createWorkspace: (name: string) => void
  openWorkspaceFolder: () => Promise<void>
}

const STORAGE_KEY = 'titanshift-workspaces-v1'

function loadInitial() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { workspaces?: Workspace[]; currentWorkspaceId?: string }
      const workspaces: Workspace[] = Array.isArray(parsed.workspaces) && parsed.workspaces.length > 0
        ? parsed.workspaces.map((w) => ({
            id: String(w.id),
            name: String(w.name),
            path: typeof w.path === 'string' ? w.path : undefined,
            source: (w.source === 'folder' ? 'folder' : 'manual') as 'folder' | 'manual',
          }))
        : [{ id: 'default', name: 'Default', source: 'manual' }]
      const currentWorkspaceId = workspaces.some((w) => w.id === parsed.currentWorkspaceId)
        ? String(parsed.currentWorkspaceId)
        : workspaces[0].id
      return { workspaces, currentWorkspaceId }
    }
  } catch {
    // ignore invalid storage
  }
  return {
    workspaces: [{ id: 'default', name: 'Default', source: 'manual' }],
    currentWorkspaceId: 'default',
  } as { workspaces: Workspace[]; currentWorkspaceId: string }
}

const initial = loadInitial()

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: initial.workspaces,
  currentWorkspaceId: initial.currentWorkspaceId,
  currentWorkspaceName: 'Default',
  currentWorkspacePath: null,
  selectWorkspace: () => {},
  createWorkspace: () => {},
  openWorkspaceFolder: async () => {},
})

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [{ workspaces, currentWorkspaceId }, setState] = useState(loadInitial)

  function moveWorkspaceToFront(items: Workspace[], id: string): Workspace[] {
    const index = items.findIndex((w) => w.id === id)
    if (index <= 0) return items
    const next = items.slice()
    const [selected] = next.splice(index, 1)
    next.unshift(selected)
    return next
  }

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ workspaces, currentWorkspaceId }))
  }, [workspaces, currentWorkspaceId])

  const currentWorkspace = useMemo(
    () => workspaces.find((w) => w.id === currentWorkspaceId),
    [workspaces, currentWorkspaceId],
  )
  const currentWorkspaceName = currentWorkspace?.name ?? 'Default'
  const currentWorkspacePath = currentWorkspace?.path ?? null

  // Sync workspace root with backend whenever active workspace path changes
  const syncBackendRoot = useCallback(async (path: string) => {
    try {
      await fetch('/api/workspace/set-root', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
    } catch {
      // best-effort; backend may not be running yet
    }
  }, [])

  useEffect(() => {
    if (currentWorkspacePath) {
      void syncBackendRoot(currentWorkspacePath)
    }
  }, [currentWorkspacePath, syncBackendRoot])

  function selectWorkspace(id: string) {
    setState((prev) => ({
      workspaces: prev.workspaces.some((w) => w.id === id) ? moveWorkspaceToFront(prev.workspaces, id) : prev.workspaces,
      currentWorkspaceId: prev.workspaces.some((w) => w.id === id) ? id : prev.currentWorkspaceId,
    }))
  }

  function createWorkspace(name: string) {
    const nextName = name.trim()
    if (!nextName) return
    const id = nextName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || `workspace-${Date.now()}`
    setState((prev) => {
      if (prev.workspaces.some((w) => w.id === id)) {
        return { workspaces: moveWorkspaceToFront(prev.workspaces, id), currentWorkspaceId: id }
      }
      const next = [{ id, name: nextName, source: 'manual' as const }, ...prev.workspaces]
      return { workspaces: next, currentWorkspaceId: id }
    })
  }

  async function openWorkspaceFolder() {
    const folderPath = window.prompt(
      'Enter the full path to the workspace folder (e.g. D:\\Projects\\MyProject):',
    )
    if (!folderPath || !folderPath.trim()) return

    const trimmed = folderPath.trim()
    const folderName = trimmed.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? trimmed
    const id = folderName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || `workspace-${Date.now()}`

    setState((prev) => {
      const existing = prev.workspaces.find((w) => w.id === id)
      if (existing) {
        // Update path if it changed
        const updated = prev.workspaces.map((w) => w.id === id ? { ...w, path: trimmed } : w)
        return { workspaces: moveWorkspaceToFront(updated, id), currentWorkspaceId: id }
      }
      return {
        workspaces: [{ id, name: folderName, path: trimmed, source: 'folder' }, ...prev.workspaces],
        currentWorkspaceId: id,
      }
    })
  }

  return (
    <WorkspaceContext.Provider value={{ workspaces, currentWorkspaceId, currentWorkspaceName, currentWorkspacePath, selectWorkspace, createWorkspace, openWorkspaceFolder }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}