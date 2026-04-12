import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

interface Workspace {
  id: string
  name: string
}

interface WorkspaceContextValue {
  workspaces: Workspace[]
  currentWorkspaceId: string
  currentWorkspaceName: string
  selectWorkspace: (id: string) => void
  createWorkspace: (name: string) => void
}

const STORAGE_KEY = 'titanshift-workspaces-v1'

function loadInitial() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { workspaces?: Workspace[]; currentWorkspaceId?: string }
      const workspaces = Array.isArray(parsed.workspaces) && parsed.workspaces.length > 0
        ? parsed.workspaces
        : [{ id: 'default', name: 'Default' }]
      const currentWorkspaceId = workspaces.some((w) => w.id === parsed.currentWorkspaceId)
        ? String(parsed.currentWorkspaceId)
        : workspaces[0].id
      return { workspaces, currentWorkspaceId }
    }
  } catch {
    // ignore invalid storage
  }
  return {
    workspaces: [{ id: 'default', name: 'Default' }],
    currentWorkspaceId: 'default',
  }
}

const initial = loadInitial()

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: initial.workspaces,
  currentWorkspaceId: initial.currentWorkspaceId,
  currentWorkspaceName: 'Default',
  selectWorkspace: () => {},
  createWorkspace: () => {},
})

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [{ workspaces, currentWorkspaceId }, setState] = useState(loadInitial)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ workspaces, currentWorkspaceId }))
  }, [workspaces, currentWorkspaceId])

  const currentWorkspaceName = useMemo(
    () => workspaces.find((w) => w.id === currentWorkspaceId)?.name ?? 'Default',
    [workspaces, currentWorkspaceId],
  )

  function selectWorkspace(id: string) {
    setState((prev) => ({
      workspaces: prev.workspaces,
      currentWorkspaceId: prev.workspaces.some((w) => w.id === id) ? id : prev.currentWorkspaceId,
    }))
  }

  function createWorkspace(name: string) {
    const nextName = name.trim()
    if (!nextName) return
    const id = nextName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || `workspace-${Date.now()}`
    setState((prev) => {
      if (prev.workspaces.some((w) => w.id === id)) {
        return { workspaces: prev.workspaces, currentWorkspaceId: id }
      }
      const next = [...prev.workspaces, { id, name: nextName }]
      return { workspaces: next, currentWorkspaceId: id }
    })
  }

  return (
    <WorkspaceContext.Provider value={{ workspaces, currentWorkspaceId, currentWorkspaceName, selectWorkspace, createWorkspace }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}