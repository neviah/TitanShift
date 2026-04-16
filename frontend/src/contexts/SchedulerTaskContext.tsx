import { createContext, useContext, useEffect, useState, useRef, type ReactNode } from 'react'
import { useWorkspace } from './WorkspaceContext'
import { useToast } from './ToastContext'

export interface SchedulerTask {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  description?: string
  created_at?: string
  updated_at?: string
  tools_used?: string[]
  workflow_phase?: string
}

interface SchedulerTaskContextValue {
  currentTask: SchedulerTask | null
  isTaskRunning: boolean
  taskHistory: SchedulerTask[]
  refreshTasks: () => Promise<void>
  concurrencyMode: 'single-run' | 'parallel'
  setConcurrencyMode: (mode: 'single-run' | 'parallel') => void
}

const SchedulerTaskContext = createContext<SchedulerTaskContextValue | undefined>(undefined)

const STORAGE_KEY = 'titanshift-scheduler-concurrency'
const POLL_INTERVAL = 5000 // 5 seconds

export function SchedulerTaskProvider({ children }: { children: ReactNode }) {
  const { workspace } = useWorkspace()
  const { addToast } = useToast()
  const [currentTask, setCurrentTask] = useState<SchedulerTask | null>(null)
  const [taskHistory, setTaskHistory] = useState<SchedulerTask[]>([])
  const [concurrencyMode, setConcurrencyModeState] = useState<'single-run' | 'parallel'>(
    () => (localStorage.getItem(STORAGE_KEY) as 'single-run' | 'parallel' | null) || 'single-run'
  )
  const previousTaskRef = useRef<SchedulerTask | null>(null)

  // Fetch current running task
  const refreshTasks = async () => {
    if (!workspace?.id) return

    try {
      const response = await fetch('/tasks', {
        headers: {
          'x-api-key': localStorage.getItem('api-key') || 'read123',
        },
      })
      if (!response.ok) return

      const data = await response.json()
      if (data.tasks && Array.isArray(data.tasks)) {
        // Find the most recent running or just-completed task
        const sortedTasks = data.tasks.sort(
          (a: SchedulerTask, b: SchedulerTask) =>
            new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
        )

        // Current task is the newest one
        const newest = sortedTasks[0]
        const newCurrent =
          newest && (newest.status === 'running' || newest.status === 'pending') ? newest : null

        // Emit notifications on state changes
        if (previousTaskRef.current && newCurrent) {
          // Task transitioned from running to completed/failed
          if (previousTaskRef.current.status === 'running' && newCurrent.status === 'completed') {
            addToast(`Task completed: ${newCurrent.description || 'Task'}`, 'success')
          } else if (previousTaskRef.current.status === 'running' && newCurrent.status === 'failed') {
            addToast(`Task failed: ${newCurrent.description || 'Task'}`, 'error')
          }
        } else if (!previousTaskRef.current && newCurrent && newCurrent.status === 'running') {
          // New task started
          addToast(`Task started: ${newCurrent.description || 'Task'}`, 'info')
        }

        setCurrentTask(newCurrent)
        previousTaskRef.current = newCurrent
        setTaskHistory(sortedTasks.slice(0, 10)) // Keep last 10
      }
    } catch (error) {
      console.error('Failed to fetch scheduler tasks:', error)
    }
  }

  // Poll for task updates
  useEffect(() => {
    refreshTasks()
    const interval = setInterval(refreshTasks, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [workspace?.id])

  const setConcurrencyMode = (mode: 'single-run' | 'parallel') => {
    setConcurrencyModeState(mode)
    localStorage.setItem(STORAGE_KEY, mode)
  }

  const value: SchedulerTaskContextValue = {
    currentTask,
    isTaskRunning: currentTask !== null && currentTask.status === 'running',
    taskHistory,
    refreshTasks,
    concurrencyMode,
    setConcurrencyMode,
  }

  return (
    <SchedulerTaskContext.Provider value={value}>{children}</SchedulerTaskContext.Provider>
  )
}

export function useSchedulerTask() {
  const context = useContext(SchedulerTaskContext)
  if (!context) {
    throw new Error('useSchedulerTask must be used within SchedulerTaskProvider')
  }
  return context
}
