import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

interface Workspace {
  id: string
  name: string
  source: 'manual' | 'folder'
}

interface WorkspaceContextValue {
  workspaces: Workspace[]
  currentWorkspaceId: string
  currentWorkspaceName: string
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
  selectWorkspace: () => {},
  createWorkspace: () => {},
  openWorkspaceFolder: async () => {},
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
      const next = [...prev.workspaces, { id, name: nextName, source: 'manual' as const }]
      return { workspaces: next, currentWorkspaceId: id }
    })
  }

  async function openWorkspaceFolder() {
    const picker = (window as { showDirectoryPicker?: () => Promise<{ name?: string }> }).showDirectoryPicker
    if (!picker) {
      const fallback = window.prompt('Folder picker is unavailable. Enter workspace name')
      if (typeof fallback === 'string') createWorkspace(fallback)
      return
    }

    try {
      const handle = await picker()
      const folderName = String(handle?.name ?? '').trim() || `workspace-${Date.now()}`
      const id = folderName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || `workspace-${Date.now()}`
      setState((prev) => {
        const existing = prev.workspaces.find((w) => w.id === id)
        if (existing) {
          return { workspaces: prev.workspaces, currentWorkspaceId: existing.id }
        }
        return {
          workspaces: [...prev.workspaces, { id, name: folderName, source: 'folder' }],
          currentWorkspaceId: id,
        }
      })
    } catch {
      // user canceled picker
    }
  }

  return (
    <WorkspaceContext.Provider value={{ workspaces, currentWorkspaceId, currentWorkspaceName, selectWorkspace, createWorkspace, openWorkspaceFolder }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}