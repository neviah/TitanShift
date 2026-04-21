import {
  MessageSquare,
  ListTodo,
  Clock,
  FolderOpen,
  Zap,
  Wrench,
  Brain,
  ScrollText,
  Settings,
  KeyRound,
  ChevronRight,
  ChevronDown,
  FileText,
  Folder,
  Pencil,
  Archive,
  RotateCcw,
  Trash2,
  Briefcase,
  Play,
  Pause,
  CheckCircle,
  XCircle,
  BarChart2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { MouseEvent } from 'react'
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'
import { usePolling } from '../../hooks/usePolling'
import {
  approveArtifact,
  deleteSchedulerTaskStack,
  fetchArtifacts,
  fetchLogs,
  fetchMarketList,
  fetchMemorySummary,
  fetchRoleTemplates,
  fetchSchedulerJobs,
  fetchSchedulerTaskStacks,
  fetchTaskDetail,
  deleteTask,
  fetchTasks,
  purgeTasks,
  fetchTools,
  fetchWorkflowMetrics,
  fetchWorkspaceTree,
  revokeArtifactApproval,
  setSchedulerJobEnabled,
  triggerSchedulerTick,
} from '../../api/client'
import type { TaskScope } from '../../api/client'
import { useChatSessions } from '../../contexts/ChatSessionsContext'
import { useWorkspace } from '../../contexts/WorkspaceContext'
import type { ArtifactFile, RoleTemplate, SchedulerJob, SchedulerTaskStackJob, TaskDetail, WorkflowMetrics, WorkspaceTreeNode } from '../../api/types'

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : []
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

const RECENT_ACTIVITY_MS = 3 * 60 * 1000

function isRecentIso(value: string | null | undefined): boolean {
  if (!value) return false
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return false
  return (Date.now() - timestamp) <= RECENT_ACTIVITY_MS
}

function applyEdgeGlow(event: MouseEvent<HTMLElement>) {
  const target = event.currentTarget
  const rect = target.getBoundingClientRect()
  target.style.setProperty('--mx', `${event.clientX - rect.left}px`)
  target.style.setProperty('--my', `${event.clientY - rect.top}px`)
}

function countdownLabel(nextRunAt?: string | null): string {
  if (!nextRunAt) return 'n/a'
  const ts = Date.parse(nextRunAt)
  if (!Number.isFinite(ts)) return 'n/a'
  const remain = Math.max(0, Math.round((ts - Date.now()) / 1000))
  const mm = Math.floor(remain / 60)
  const ss = remain % 60
  return `${mm}m ${ss}s`
}

const ACTIVE_SKILLS_KEY = 'titanshift-active-skills-by-workspace-v1'
const ACTIVE_TOOLS_KEY = 'titanshift-active-tools-by-workspace-v1'

const TABS: { id: NavTab; label: string; Icon: React.FC<{ size?: number }> }[] = [
  { id: 'workspaces', label: 'Workspaces', Icon: Briefcase },
  { id: 'chat',      label: 'Chat',      Icon: MessageSquare },
  { id: 'tasks',     label: 'Tasks',     Icon: ListTodo },
  { id: 'scheduler', label: 'Scheduler', Icon: Clock },
  { id: 'files',     label: 'Files',     Icon: FolderOpen },
  { id: 'skills',    label: 'Skills',    Icon: Zap },
  { id: 'tools',     label: 'Tools',     Icon: Wrench },
  { id: 'memory',    label: 'Memory',    Icon: Brain },
  { id: 'logs',      label: 'Logs',      Icon: ScrollText },
]

interface LeftPaneProps {
  activeTab: NavTab
  onTabChange: (tab: NavTab) => void
  onOpenFile: (path: string) => void
  selectedFilePath: string | null
}

export function LeftPane({ activeTab, onTabChange, onOpenFile, selectedFilePath }: LeftPaneProps) {
  const { workspaces, currentWorkspaceId, currentWorkspaceName, currentWorkspacePath, selectWorkspace, openWorkspaceFolder } = useWorkspace()
  const [taskScope, setTaskScope] = useState<TaskScope>('workspace')
  const { data: taskData, refresh: refreshTasks } = usePolling(() => fetchTasks(taskScope), { interval: 8000 })
  const { data: skillsData } = usePolling(fetchMarketList, { interval: 30000 })
  const { data: treeData, refresh: refreshTree } = usePolling(fetchWorkspaceTree, { interval: 8000 })
  const { data: toolsData } = usePolling(fetchTools, { interval: 30000 })
  const { data: memoryData } = usePolling(fetchMemorySummary, { interval: 30000 })
  const { data: logsData } = usePolling(() => fetchLogs(12), { interval: 10000 })
  const { data: roleTemplatesData } = usePolling(fetchRoleTemplates, { interval: 30000 })
  const { data: schedulerJobsData, refresh: refreshSchedulerJobs } = usePolling(fetchSchedulerJobs, { interval: 5000 })
  const { data: schedulerTaskStacksData, refresh: refreshSchedulerTaskStacks } = usePolling(fetchSchedulerTaskStacks, { interval: 5000 })
  const { data: artifactsData, refresh: refreshArtifacts } = usePolling(fetchArtifacts, { interval: 15000 })
  const { data: metricsData } = usePolling(fetchWorkflowMetrics, { interval: 15000 })
  const [artifactBusy, setArtifactBusy] = useState<string | null>(null)
  const { sessions, currentSessionId, createSession, selectSession, renameSession, archiveSession, restoreSession, deleteSession } = useChatSessions()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [pendingDeleteTaskId, setPendingDeleteTaskId] = useState<string | null>(null)
  const [taskDeleteMode, setTaskDeleteMode] = useState(false)
  const [selectedTaskIds, setSelectedTaskIds] = useState<Record<string, boolean>>({})
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null)
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({})
  const [schedulerBusyId, setSchedulerBusyId] = useState<string | null>(null)
  const [activeSkillsByWorkspace, setActiveSkillsByWorkspace] = useState<Record<string, Record<string, boolean>>>(() => {
    try {
      return JSON.parse(localStorage.getItem(ACTIVE_SKILLS_KEY) ?? '{}') as Record<string, Record<string, boolean>>
    } catch {
      return {}
    }
  })
  const [activeToolsByWorkspace, setActiveToolsByWorkspace] = useState<Record<string, Record<string, boolean>>>(() => {
    try {
      return JSON.parse(localStorage.getItem(ACTIVE_TOOLS_KEY) ?? '{}') as Record<string, Record<string, boolean>>
    } catch {
      return {}
    }
  })

  const totalTaskCount = taskData?.length ?? 0
  const tasks = (taskData ?? []).slice(0, 12)
  const installedSkills = (skillsData ?? []).filter((s) => s.installed).slice(0, 12)
  const recentSessions = useMemo(
    () => sessions.filter((s) => !s.archived).slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 12),
    [sessions],
  )
  const archivedSessions = useMemo(
    () => sessions.filter((s) => s.archived).slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 12),
    [sessions],
  )
  const activeSkills = activeSkillsByWorkspace[currentWorkspaceId] ?? {}
  const activeTools = activeToolsByWorkspace[currentWorkspaceId] ?? {}
  const roleTemplates: RoleTemplate[] = roleTemplatesData ?? []
  const schedulerJobs: SchedulerJob[] = schedulerJobsData ?? []
  const schedulerTaskStacks: SchedulerTaskStackJob[] = schedulerTaskStacksData ?? []
  const schedulerTaskStackIds = useMemo(() => new Set(schedulerTaskStacks.map((j) => j.job_id)), [schedulerTaskStacks])
  const artifacts: ArtifactFile[] = artifactsData ?? []
  const workflowMetrics: WorkflowMetrics | null = metricsData ?? null
  const latestTask = tasks[0] ?? null
  const selectedDeleteCount = useMemo(
    () => Object.values(selectedTaskIds).filter(Boolean).length,
    [selectedTaskIds],
  )
  const livePulse = (logsData?.items ?? []).some((entry) => {
    const eventType = String(entry.event_type ?? '').toLowerCase()
    return isRecentIso(entry.timestamp) && (eventType.includes('task_') || eventType.includes('workflow_'))
  })
  const anchorMeta = useMemo(() => {
    if (activeTab === 'workspaces') return { title: 'Workspace Anchor', subtitle: `${workspaces.length} workspace profiles`, hint: currentWorkspaceName }
    if (activeTab === 'chat') return { title: 'Conversation Anchor', subtitle: `${recentSessions.length} active threads`, hint: currentWorkspaceName }
    if (activeTab === 'tasks') return { title: 'Task Queue', subtitle: `${totalTaskCount} tracked tasks (${taskScope === 'workspace' ? 'this workspace' : 'all workspaces'})`, hint: latestTask?.status ?? 'idle' }
    if (activeTab === 'files') return { title: 'File Anchor', subtitle: `${treeData?.length ?? 0} root nodes`, hint: currentWorkspaceName }
    if (activeTab === 'skills') return { title: 'Skill Anchor', subtitle: `${installedSkills.length} installed`, hint: currentWorkspaceName }
    if (activeTab === 'tools') return { title: 'Tool Anchor', subtitle: `${(toolsData ?? []).length} discovered`, hint: currentWorkspaceName }
    if (activeTab === 'memory') return { title: 'Memory Anchor', subtitle: `${memoryData?.working_entries ?? 0} working entries`, hint: 'runtime memory summary' }
    if (activeTab === 'logs') return { title: 'Log Anchor', subtitle: `${logsData?.items?.length ?? 0} recent events`, hint: 'live telemetry feed' }
    if (activeTab === 'scheduler') return { title: 'Scheduler Anchor', subtitle: 'Job timeline and heartbeat', hint: 'scheduler panel' }
    return { title: 'Settings Anchor', subtitle: 'Runtime and provider controls', hint: 'configuration' }
  }, [activeTab, workspaces.length, currentWorkspaceName, recentSessions.length, totalTaskCount, taskScope, latestTask?.status, treeData?.length, installedSkills.length, toolsData, memoryData?.working_entries, logsData?.items?.length])

  async function setArtifactApproval(artifactType: 'spec' | 'plan', approve: boolean) {
    const busyKey = `${artifactType}:${approve ? 'approve' : 'revoke'}`
    setArtifactBusy(busyKey)
    try {
      if (approve) {
        await approveArtifact(artifactType)
      } else {
        await revokeArtifactApproval(artifactType)
      }
      await refreshArtifacts()
    } finally {
      setArtifactBusy(null)
    }
  }
  useEffect(() => {
    localStorage.setItem(ACTIVE_SKILLS_KEY, JSON.stringify(activeSkillsByWorkspace))
  }, [activeSkillsByWorkspace])

  useEffect(() => {
    localStorage.setItem(ACTIVE_TOOLS_KEY, JSON.stringify(activeToolsByWorkspace))
  }, [activeToolsByWorkspace])

  useEffect(() => {
    void refreshTree()
  }, [currentWorkspaceId, currentWorkspacePath, refreshTree])

  useEffect(() => {
    if (!selectedTaskId && tasks.length > 0) {
      setSelectedTaskId(tasks[0].task_id)
    }
  }, [tasks, selectedTaskId])

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTask(null)
      return
    }
    let mounted = true
    void fetchTaskDetail(selectedTaskId, taskScope)
      .then((task) => {
        if (mounted) setSelectedTask(task)
      })
      .catch(() => {
        if (mounted) setSelectedTask(null)
      })
    return () => {
      mounted = false
    }
  }, [selectedTaskId, taskScope])

  useEffect(() => {
    const visibleTaskIds = new Set(tasks.map((task) => task.task_id))
    setSelectedTaskIds((prev) => {
      const next: Record<string, boolean> = {}
      for (const [taskId, selected] of Object.entries(prev)) {
        if (visibleTaskIds.has(taskId) && selected) {
          next[taskId] = true
        }
      }
      return next
    })
  }, [tasks])

  function handleNewChat() {
    createSession()
    onTabChange('chat')
  }

  function togglePath(path: string) {
    setExpandedPaths((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  function handleRename(id: string, title: string) {
    const next = window.prompt('Rename chat thread', title)
    if (typeof next === 'string') {
      renameSession(id, next)
    }
  }

  function requestTaskDelete(taskId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    setPendingDeleteTaskId(taskId)
  }

  function cancelTaskDelete(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    setPendingDeleteTaskId(null)
  }

  function confirmTaskDelete(taskId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    void deleteTask(taskId, taskScope)
      .then(() => {
        if (selectedTaskId === taskId) {
          setSelectedTaskId(null)
          setSelectedTask(null)
        }
      })
      .catch(() => {})
      .finally(() => {
        setPendingDeleteTaskId(null)
      })
  }

  function switchTaskScope(scope: TaskScope) {
    setTaskScope(scope)
    setSelectedTaskId(null)
    setSelectedTask(null)
    setSelectedTaskIds({})
    setPendingDeleteTaskId(null)
  }

  function enterTaskDeleteMode() {
    setTaskDeleteMode(true)
    setPendingDeleteTaskId(null)
    setSelectedTaskIds({})
  }

  function exitTaskDeleteMode() {
    setTaskDeleteMode(false)
    setSelectedTaskIds({})
  }

  function toggleTaskSelection(taskId: string) {
    setSelectedTaskIds((prev) => ({
      ...prev,
      [taskId]: !prev[taskId],
    }))
  }

  function selectAllVisibleTasks() {
    const allSelected: Record<string, boolean> = {}
    for (const task of tasks) {
      allSelected[task.task_id] = true
    }
    setSelectedTaskIds(allSelected)
  }

  async function deleteSelectedTasks() {
    const ids = Object.entries(selectedTaskIds)
      .filter(([, selected]) => selected)
      .map(([taskId]) => taskId)
    if (ids.length === 0) return

    await Promise.all(ids.map((taskId) => deleteTask(taskId, taskScope).catch(() => undefined)))

    if (selectedTaskId && ids.includes(selectedTaskId)) {
      setSelectedTaskId(null)
      setSelectedTask(null)
    }

    setSelectedTaskIds({})
    setTaskDeleteMode(false)
    await refreshTasks()
  }

  async function purgeTaskHistory() {
    const scopeLabel = taskScope === 'workspace' ? `this workspace (${currentWorkspaceName})` : 'all workspaces'
    const confirmed = window.confirm(`Delete all ${totalTaskCount} tasks in ${scopeLabel}? This cannot be undone.`)
    if (!confirmed) return

    await purgeTasks(taskScope)

    setPendingDeleteTaskId(null)
    setSelectedTaskIds({})
    setTaskDeleteMode(false)
    setSelectedTaskId(null)
    setSelectedTask(null)
    await refreshTasks()
  }

  function toggleSkillActive(skillId: string) {
    setActiveSkillsByWorkspace((prev) => ({
      ...prev,
      [currentWorkspaceId]: {
        ...(prev[currentWorkspaceId] ?? {}),
        [skillId]: !(prev[currentWorkspaceId]?.[skillId] ?? false),
      },
    }))
  }

  function toggleToolActive(toolName: string) {
    setActiveToolsByWorkspace((prev) => ({
      ...prev,
      [currentWorkspaceId]: {
        ...(prev[currentWorkspaceId] ?? {}),
        [toolName]: !(prev[currentWorkspaceId]?.[toolName] ?? false),
      },
    }))
  }

  async function toggleSchedulerJob(job: SchedulerJob) {
    setSchedulerBusyId(job.job_id)
    try {
      await setSchedulerJobEnabled(job.job_id, !job.enabled)
      await triggerSchedulerTick().catch(() => undefined)
      await refreshSchedulerJobs()
      await refreshSchedulerTaskStacks()
    } finally {
      setSchedulerBusyId(null)
    }
  }

  async function deleteSchedulerBinding(jobId: string) {
    setSchedulerBusyId(jobId)
    try {
      await deleteSchedulerTaskStack(jobId)
      await refreshSchedulerJobs()
      await refreshSchedulerTaskStacks()
    } finally {
      setSchedulerBusyId(null)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className={styles.logo}>TitanShift</span>
      </div>

      <nav className={styles.nav}>
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`${styles.tab} ${activeTab === id ? styles.active : ''}`}
            onClick={() => onTabChange(id)}
            data-tooltip={label}
            aria-label={label}
          >
            <Icon size={16} />
          </button>
        ))}
      </nav>

      <section className={styles.content}>
        <div className={`${styles.anchorCard} ${styles.edgeReactive}`} onMouseMove={applyEdgeGlow}>
          <p className={styles.anchorTitle}>{anchorMeta.title}</p>
          {activeTab === 'tasks' ? (
            <>
              <p className={styles.anchorSubtitle}>
                {taskDeleteMode
                  ? `${selectedDeleteCount} selected for deletion`
                  : anchorMeta.subtitle}
              </p>
              <div className={styles.anchorMetaRow}>
                <span className={styles.anchorHint}>Recent runs and status for the active task scope.</span>
              </div>
            </>
          ) : (
            <>
              <p className={styles.anchorSubtitle}>{anchorMeta.subtitle}</p>
              <div className={styles.anchorMetaRow}>
                <span className={`badge ${livePulse ? 'badge-warn' : 'badge-dim'}`}>{livePulse ? 'active now' : 'idle'}</span>
                <span className={styles.anchorHint}>{anchorMeta.hint}</span>
              </div>
            </>
          )}
        </div>

        {activeTab === 'workspaces' && (
          <div className={styles.list}>
            <p className={styles.sectionLabel}>Workspaces</p>
            <button className={styles.newChatBtn} onClick={() => void openWorkspaceFolder()}>New Workspace (Pick Folder)</button>
            {workspaces.map((workspace) => (
              <button
                key={workspace.id}
                className={`${styles.itemRow} ${styles.edgeReactive} ${workspace.id === currentWorkspaceId ? styles.rowActive : ''}`}
                onClick={() => selectWorkspace(workspace.id)}
                title={workspace.path ?? workspace.name}
                onMouseMove={applyEdgeGlow}
              >
                <span className={styles.rowTitle}>{workspace.name}</span>
                <span className="badge badge-dim">{workspace.source}</span>
              </button>
            ))}
          </div>
        )}

        {activeTab === 'chat' && (
          <>
            <button className={styles.newChatBtn} onClick={handleNewChat}>New Chat</button>
            <div className={styles.list}>
              <p className={styles.sectionLabel}>Recent Threads</p>
              {recentSessions.length === 0 && <p className={styles.empty}>No previous chats yet.</p>}
              {recentSessions.map((session) => (
                <div key={session.id} className={`${styles.row} ${styles.edgeReactive} ${currentSessionId === session.id ? styles.rowActive : ''} ${isRecentIso(session.updatedAt) ? styles.rowHot : ''}`} onMouseMove={applyEdgeGlow}>
                  <button
                    className={styles.rowMain}
                    title={session.title}
                    onClick={() => {
                      selectSession(session.id)
                      onTabChange('chat')
                    }}
                  >
                    <span className={styles.rowTitle}>{session.title}</span>
                    <span className={styles.rowMeta}>{session.messages.length} msgs {isRecentIso(session.updatedAt) ? '• live' : ''}</span>
                  </button>
                  <div className={styles.rowActions}>
                    <button className={styles.actionBtn} onClick={() => handleRename(session.id, session.title)} data-tooltip="Rename" aria-label="Rename chat">
                      <Pencil size={12} />
                    </button>
                    <button className={styles.actionBtn} onClick={() => archiveSession(session.id)} data-tooltip="Archive" aria-label="Archive chat">
                      <Archive size={12} />
                    </button>
                    <button className={styles.actionBtn} onClick={() => deleteSession(session.id)} data-tooltip="Delete" aria-label="Delete chat">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
              {archivedSessions.length > 0 && (
                <>
                  <p className={styles.sectionLabel}>Archived Threads</p>
                  {archivedSessions.map((session) => (
                    <div key={session.id} className={`${styles.row} ${styles.edgeReactive}`} onMouseMove={applyEdgeGlow}>
                      <button className={styles.rowMain} onClick={() => restoreSession(session.id)} title={session.title}>
                        <span className={styles.rowTitle}>{session.title}</span>
                        <span className={styles.rowMeta}>archived</span>
                      </button>
                      <div className={styles.rowActions}>
                        <button className={styles.actionBtn} onClick={() => restoreSession(session.id)} data-tooltip="Restore" aria-label="Restore chat">
                          <RotateCcw size={12} />
                        </button>
                        <button className={styles.actionBtn} onClick={() => deleteSession(session.id)} data-tooltip="Delete" aria-label="Delete chat">
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </>
        )}

        {activeTab === 'tasks' && (
          <div className={styles.list}>
            <div className={styles.taskToolbar}>
              {!taskDeleteMode ? (
                <>
                  <div className={styles.taskToolbarGroup}>
                    <button
                      className={`${styles.anchorActionBtn} ${taskScope === 'workspace' ? styles.anchorActionBtnActive : ''}`}
                      onClick={() => switchTaskScope('workspace')}
                    >
                      This Workspace
                    </button>
                    <button
                      className={`${styles.anchorActionBtn} ${taskScope === 'all' ? styles.anchorActionBtnActive : ''}`}
                      onClick={() => switchTaskScope('all')}
                    >
                      All Workspaces
                    </button>
                  </div>
                  <div className={styles.taskToolbarGroup}>
                    <button className={styles.anchorActionBtn} onClick={enterTaskDeleteMode}>Delete Tasks</button>
                    {totalTaskCount > 0 && (
                      <button className={styles.anchorDangerBtn} onClick={() => { void purgeTaskHistory() }}>
                        Clear All ({totalTaskCount})
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className={styles.taskToolbarGroup}>
                    <button className={styles.anchorActionBtn} onClick={selectAllVisibleTasks}>Select All</button>
                    <button className={styles.anchorActionBtn} onClick={exitTaskDeleteMode}>Cancel</button>
                  </div>
                  {selectedDeleteCount > 0 && (
                    <button className={styles.anchorDangerBtn} onClick={() => { void deleteSelectedTasks() }}>
                      Delete Forever
                    </button>
                  )}
                </>
              )}
            </div>
            <p className={styles.hint}>{taskScope === 'workspace' ? `Showing latest 12 tasks for ${currentWorkspaceName}` : 'Showing latest 12 tasks across all workspaces'}</p>
            {tasks.length === 0 && <p className={styles.empty}>No tasks yet.</p>}
            {tasks.map((task) => (
              <div
                key={task.task_id}
                className={`${styles.itemRow} ${styles.edgeReactive} ${selectedTaskId === task.task_id ? styles.rowActive : ''} ${task.status === 'running' ? styles.rowHot : ''}`}
                onClick={() => {
                  if (taskDeleteMode) {
                    toggleTaskSelection(task.task_id)
                  } else {
                    setSelectedTaskId(task.task_id)
                  }
                }}
                title={task.description}
                onMouseMove={applyEdgeGlow}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    if (taskDeleteMode) {
                      toggleTaskSelection(task.task_id)
                    } else {
                      setSelectedTaskId(task.task_id)
                    }
                  }
                }}
              >
                {taskDeleteMode && (
                  <input
                    type="checkbox"
                    className={styles.taskSelectCheckbox}
                    checked={Boolean(selectedTaskIds[task.task_id])}
                    onChange={() => toggleTaskSelection(task.task_id)}
                    onClick={(event) => event.stopPropagation()}
                    aria-label={`Select task ${task.description}`}
                  />
                )}
                <span className={styles.rowTitle}>{task.description}</span>
                <div className={styles.rowActions}>
                  <span className={`badge ${task.status === 'completed' ? 'badge-ok' : task.status === 'failed' ? 'badge-error' : 'badge-warn'}`}>
                    {task.status}
                  </span>
                  {!taskDeleteMode && pendingDeleteTaskId === task.task_id ? (
                    <>
                      <button
                        className={styles.actionBtn}
                        onClick={(event) => cancelTaskDelete(event)}
                        data-tooltip="Keep task"
                        aria-label="Keep task"
                      >
                        ✓
                      </button>
                      <button
                        className={styles.actionBtn}
                        onClick={(event) => confirmTaskDelete(task.task_id, event)}
                        data-tooltip="Delete task"
                        aria-label="Delete task"
                      >
                        ✕
                      </button>
                    </>
                  ) : !taskDeleteMode ? (
                    <button
                      className={styles.actionBtn}
                      onClick={(event) => requestTaskDelete(task.task_id, event)}
                      data-tooltip="Delete task"
                      aria-label="Delete task"
                    >
                      ✕
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {selectedTask && (
              <div className={styles.detailCard}>
                <p className={styles.detailTitle}>Task Detail</p>
                <p className={styles.detailLine}><span>ID</span><span className="font-mono">{selectedTask.task_id}</span></p>
                <p className={styles.detailLine}><span>Status</span><span>{selectedTask.status}</span></p>
                {typeof selectedTask.output?.workflow_mode === 'string' && (
                  <p className={styles.detailLine}><span>Workflow</span><span>{selectedTask.output.workflow_mode}</span></p>
                )}
                {selectedTask.error && <p className={`${styles.detailText} text-error`}>{selectedTask.error}</p>}
                {readStringArray(selectedTask.output?.missing_approvals).length > 0 && (
                  <div className={styles.stackBlock}>
                    <p className={styles.detailTitle}>Missing Approvals</p>
                    <div className={styles.badgeRow}>
                      {readStringArray(selectedTask.output?.missing_approvals).map((item) => (
                        <span key={item} className="badge badge-error">{item}</span>
                      ))}
                    </div>
                  </div>
                )}
                {readStringArray(selectedTask.output?.required_skill_chain).length > 0 && (
                  <div className={styles.stackBlock}>
                    <p className={styles.detailTitle}>Required Chain</p>
                    <div className={styles.badgeRow}>
                      {readStringArray(selectedTask.output?.required_skill_chain).map((item) => (
                        <span key={item} className="badge badge-dim">{item}</span>
                      ))}
                    </div>
                  </div>
                )}
                {(() => {
                  const reviewResult = readObject(selectedTask.output?.review_result)
                  const reviewTasks = Array.isArray(reviewResult.task_results) ? reviewResult.task_results : []
                  if (reviewTasks.length === 0) return null
                  return (
                    <div className={styles.stackBlock}>
                      <p className={styles.detailTitle}>Review Loop</p>
                      {reviewTasks.map((entry, index) => {
                        const row = readObject(entry)
                        return (
                          <div key={`${selectedTask.task_id}-review-${index}`} className={styles.executionItem}>
                            <div className={styles.badgeRow}>
                              <span className={`badge ${row.ok ? 'badge-ok' : 'badge-warn'}`}>{row.ok ? 'passed' : 'pending'}</span>
                              <span className="badge badge-dim">{String(row.task ?? `Task ${index + 1}`)}</span>
                              <span className="badge badge-dim">iterations {String(row.iterations ?? 0)}</span>
                            </div>
                            <p className={styles.detailText}>Implementer: {String(row.implementer_agent_id ?? 'n/a')}</p>
                            {typeof row.spec_reviewer_agent_id === 'string' && <p className={styles.detailText}>Spec reviewer: {row.spec_reviewer_agent_id}</p>}
                            {typeof row.code_reviewer_agent_id === 'string' && <p className={styles.detailText}>Code reviewer: {row.code_reviewer_agent_id}</p>}
                            {typeof row.verifier_agent_id === 'string' && <p className={styles.detailText}>Verifier: {row.verifier_agent_id}</p>}
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}
                {typeof selectedTask.output?.response === 'string' && selectedTask.output.response.length > 0 && (
                  <p className={styles.detailText}>{selectedTask.output.response}</p>
                )}
              </div>
            )}
            {roleTemplates.length > 0 && (
              <div className={styles.detailCard}>
                <p className={styles.detailTitle}>Role Templates</p>
                {roleTemplates.map((role) => (
                  <div key={role.role_key} className={styles.executionItem}>
                    <p className={styles.detailLine}><span>{role.role_name}</span><span className="badge badge-dim">{role.role_key}</span></p>
                    <p className={styles.detailText}>{role.goal}</p>
                    <div className={styles.badgeRow}>
                      {role.required_skills.map((skill) => (
                        <span key={`${role.role_key}-${skill}`} className="badge badge-ok">{skill}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className={styles.detailCard}>
              <p className={styles.detailTitle}>Artifact Lifecycle</p>
              <p className={styles.hint}>Approve plan/spec artifacts once and Superpowered gates can use the persisted state.</p>
              {artifacts.length === 0 && <p className={styles.empty}>No artifacts found in documents/specs or documents/plans.</p>}
              {artifacts.map((artifact) => (
                <div key={artifact.path} className={styles.executionItem}>
                  <p className={styles.detailLine}>
                    <span>{artifact.filename}</span>
                    <span className={`badge ${artifact.approved ? 'badge-ok' : 'badge-warn'}`}>
                      {artifact.approved ? 'approved' : 'pending'}
                    </span>
                  </p>
                  <p className={styles.detailText}>{artifact.path}</p>
                  <div className={styles.badgeRow}>
                    <span className="badge badge-dim">{artifact.artifact_type}</span>
                    <span className="badge badge-dim">{Math.max(1, Math.round(artifact.size / 1024))} KB</span>
                    <button
                      className={styles.smallAction}
                      disabled={artifactBusy !== null}
                      onClick={() => void setArtifactApproval(artifact.artifact_type, true)}
                    >
                      <CheckCircle size={14} /> Approve
                    </button>
                    <button
                      className={styles.smallAction}
                      disabled={artifactBusy !== null}
                      onClick={() => void setArtifactApproval(artifact.artifact_type, false)}
                    >
                      <XCircle size={14} /> Revoke
                    </button>
                  </div>
                </div>
              ))}
            </div>
            {workflowMetrics && (
              <div className={styles.detailCard}>
                <p className={styles.detailTitle}>Workflow Metrics</p>
                <div className={styles.badgeRow}>
                  <span className="badge badge-dim"><BarChart2 size={12} /> total tasks {workflowMetrics.total_tasks}</span>
                </div>
                <div className={styles.stackBlock}>
                  <p className={styles.detailLine}><span>Lightning tasks</span><span>{workflowMetrics.lightning.total_tasks}</span></p>
                  <p className={styles.detailLine}><span>Lightning avg duration</span><span>{workflowMetrics.lightning.avg_duration_ms}ms</span></p>
                  <p className={styles.detailLine}><span>Superpowered tasks</span><span>{workflowMetrics.superpowered.total_tasks}</span></p>
                  <p className={styles.detailLine}><span>Superpowered avg duration</span><span>{workflowMetrics.superpowered.avg_duration_ms}ms</span></p>
                  <p className={styles.detailLine}><span>Gate blocks</span><span>{workflowMetrics.superpowered.gate_blocked_count}</span></p>
                  <p className={styles.detailLine}><span>Reviews run</span><span>{workflowMetrics.superpowered.review_ran_count}</span></p>
                  <p className={styles.detailLine}><span>Review pass rate</span><span>{workflowMetrics.superpowered.review_pass_rate ?? 'n/a'}</span></p>
                  <p className={styles.detailLine}><span>Avg review iterations</span><span>{workflowMetrics.superpowered.avg_review_iterations ?? 'n/a'}</span></p>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'files' && (
          <div className={styles.list}>
            <p className={styles.hint}>Workspace tree</p>
            {currentWorkspacePath
              ? <p className={styles.hint} title={currentWorkspacePath} style={{ fontSize: 10, wordBreak: 'break-all', opacity: 0.7 }}>{currentWorkspacePath}</p>
              : <p className={styles.hint} style={{ fontSize: 10, opacity: 0.5 }}>Workspace path not bound yet. Select this workspace again to bind a folder path.</p>
            }
            {!treeData || treeData.length === 0 ? <p className={styles.empty}>No files available.</p> : (
              <div className={styles.tree}>
                {treeData.map((node) => (
                  <TreeNode key={node.path} node={node} expandedPaths={expandedPaths} onToggle={togglePath} onOpenFile={onOpenFile} selectedFilePath={selectedFilePath} />
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'skills' && (
          <div className={styles.list}>
            <p className={styles.hint}>Installed skills</p>
            <p className={styles.hint}>Active in workspace: {currentWorkspaceName}</p>
            {installedSkills.length === 0 && <p className={styles.empty}>No installed skills yet.</p>}
            {installedSkills.map((skill) => (
              <button key={skill.id} className={styles.itemRow} onClick={() => toggleSkillActive(skill.id)} title={`Toggle active for ${currentWorkspaceName}`}>
                <span className={styles.rowTitle}>{skill.name}</span>
                <span className="badge badge-ok">installed</span>
                <span className={`badge ${activeSkills[skill.id] ? 'badge-ok' : 'badge-dim'}`}>{activeSkills[skill.id] ? 'active' : 'inactive'}</span>
              </button>
            ))}
            <p className={styles.hint}>Marketplace is shown in the center pane.</p>
          </div>
        )}

        {activeTab === 'tools' && (
          <div className={styles.list}>
            <p className={styles.hint}>Available tools</p>
            <p className={styles.hint}>Active in workspace: {currentWorkspaceName}</p>
            {(toolsData ?? []).slice(0, 14).map((tool) => (
              <button key={tool.name} className={styles.itemRow} onClick={() => toggleToolActive(tool.name)} title={`Toggle active for ${currentWorkspaceName}`}>
                <span className={styles.rowTitle}>{tool.name}</span>
                <span className={`badge ${tool.allowed_by_policy ? 'badge-ok' : 'badge-error'}`}>{tool.allowed_by_policy ? 'allowed' : 'blocked'}</span>
                <span className={`badge ${activeTools[tool.name] ? 'badge-ok' : 'badge-dim'}`}>{activeTools[tool.name] ? 'active' : 'inactive'}</span>
              </button>
            ))}
          </div>
        )}

        {activeTab === 'memory' && (
          <div className={styles.list}>
            <p className={styles.hint}>Memory summary</p>
            {memoryData ? (
              <div className={styles.detailCard}>
                <p className={styles.detailLine}><span>Working agents</span><span>{memoryData.working_agents}</span></p>
                <p className={styles.detailLine}><span>Working entries</span><span>{memoryData.working_entries}</span></p>
                <p className={styles.detailLine}><span>Short-term agents</span><span>{memoryData.short_term_agents}</span></p>
                <p className={styles.detailLine}><span>Short-term entries</span><span>{memoryData.short_term_entries}</span></p>
                <p className={styles.detailLine}><span>Long-term scopes</span><span>{memoryData.long_term_scopes}</span></p>
                <p className={styles.detailLine}><span>Long-term entries</span><span>{memoryData.long_term_entries}</span></p>
              </div>
            ) : <p className={styles.empty}>No memory data yet.</p>}
          </div>
        )}

        {activeTab === 'logs' && (
          <div className={styles.list}>
            <p className={styles.hint}>Recent logs</p>
            {(logsData?.items ?? []).slice(0, 12).map((entry, index) => (
              <div key={`${entry.timestamp}-${entry.event_type}-${index}`} className={styles.row}>
                <span className={styles.rowTitle}>{entry.event_type}</span>
                <span className={styles.rowMeta}>{new Date(entry.timestamp).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'scheduler' && (
          <div className={styles.list}>
            <p className={styles.hint}>Scheduler runtime jobs</p>
            {schedulerJobs.length === 0 ? (
              <p className={styles.empty}>No scheduler jobs yet.</p>
            ) : (
              schedulerJobs.slice(0, 20).map((job) => (
                <div key={job.job_id} className={`${styles.row} ${job.is_running ? styles.rowHot : ''}`}>
                  <button type="button" className={styles.rowMain}>
                    <span className={styles.rowTitle}>{job.job_id}</span>
                    <span className={styles.rowMeta}>
                      {job.is_running ? 'running now' : `next in ${countdownLabel(job.next_run_at)}`} • {job.enabled ? 'enabled' : 'disabled'}
                    </span>
                  </button>
                  <div className={styles.rowActions}>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      data-tooltip={job.enabled ? 'Disable job' : 'Enable job'}
                      onClick={() => { void toggleSchedulerJob(job) }}
                      disabled={schedulerBusyId === job.job_id}
                    >
                      {job.enabled ? <Pause size={13} /> : <Play size={13} />}
                    </button>
                    {schedulerTaskStackIds.has(job.job_id) && (
                      <button
                        type="button"
                        className={styles.actionBtn}
                        data-tooltip="Delete binding"
                        onClick={() => { void deleteSchedulerBinding(job.job_id) }}
                        disabled={schedulerBusyId === job.job_id}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'settings' && (
          <div className={styles.list}>
            <p className={styles.hint}>Settings are open in the center pane.</p>
          </div>
        )}

        {activeTab === 'keys' && (
          <div className={styles.list}>
            <p className={styles.hint}>API Keys are open in the center pane.</p>
          </div>
        )}
      </section>

      <div className={styles.pulseStrip}>
        <span className={`${styles.pulseDot} ${livePulse ? styles.pulseDotLive : ''}`} />
        <span className={styles.pulseText}>
          {livePulse
            ? `Current run active${latestTask ? ` • ${latestTask.status}` : ''}`
            : 'Current run idle'}
        </span>
      </div>

      <div className={styles.footer}>
        <button
          className={`${styles.tab} ${activeTab === 'keys' ? styles.active : ''}`}
          onClick={() => onTabChange('keys')}
          data-tooltip="API Keys"
          aria-label="API Keys"
        >
          <KeyRound size={16} />
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'settings' ? styles.active : ''}`}
          onClick={() => onTabChange('settings')}
          data-tooltip="Settings"
          aria-label="Settings"
        >
          <Settings size={16} />
        </button>
      </div>
    </div>
  )
}

function TreeNode({
  node,
  expandedPaths,
  onToggle,
  onOpenFile,
  selectedFilePath,
  depth = 0,
}: {
  node: WorkspaceTreeNode
  expandedPaths: Record<string, boolean>
  onToggle: (path: string) => void
  onOpenFile: (path: string) => void
  selectedFilePath: string | null
  depth?: number
}) {
  const isOpen = expandedPaths[node.path] ?? depth < 1

  if (!node.is_dir) {
    return (
      <button className={`${styles.treeRowButton} ${selectedFilePath === node.path ? styles.rowActive : ''}`} style={{ paddingLeft: `${depth * 14 + 6}px` }} title={node.path} onClick={() => onOpenFile(node.path)}>
        <FileText size={13} className={styles.treeIcon} />
        <span className={styles.treeLabel}>{node.name}</span>
      </button>
    )
  }

  return (
    <div>
      <button className={styles.treeRowButton} style={{ paddingLeft: `${depth * 14 + 6}px` }} onClick={() => onToggle(node.path)} title={node.path}>
        {isOpen ? <ChevronDown size={13} className={styles.treeIcon} /> : <ChevronRight size={13} className={styles.treeIcon} />}
        <Folder size={13} className={styles.treeIcon} />
        <span className={styles.treeLabel}>{node.name}</span>
      </button>
      {isOpen && node.children?.map((child) => (
        <TreeNode key={child.path} node={child} expandedPaths={expandedPaths} onToggle={onToggle} onOpenFile={onOpenFile} selectedFilePath={selectedFilePath} depth={depth + 1} />
      ))}
    </div>
  )
}
