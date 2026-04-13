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
  Plus,
  ArrowUp,
  ArrowDown,
  CheckCircle,
  XCircle,
  BarChart2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { MouseEvent } from 'react'
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'
import { usePolling } from '../../hooks/usePolling'
import { approveArtifact, fetchArtifacts, fetchConfig, fetchLogs, fetchMarketList, fetchMemorySummary, fetchRoleTemplates, fetchTaskDetail, fetchTasks, fetchTools, fetchWorkflowMetrics, fetchWorkspaceTree, revokeArtifactApproval, sendChat } from '../../api/client'
import { useChatSessions } from '../../contexts/ChatSessionsContext'
import { useTaskDrafts, type TaskDraft } from '../../contexts/TaskDraftsContext'
import { useWorkspace } from '../../contexts/WorkspaceContext'
import type { ArtifactFile, RoleTemplate, TaskDetail, WorkflowMetrics, WorkspaceTreeNode } from '../../api/types'

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
  const { data: taskData } = usePolling(fetchTasks, { interval: 8000 })
  const { data: skillsData } = usePolling(fetchMarketList, { interval: 30000 })
  const { data: treeData, refresh: refreshTree } = usePolling(fetchWorkspaceTree, { interval: 30000 })
  const { data: toolsData } = usePolling(fetchTools, { interval: 30000 })
  const { data: memoryData } = usePolling(fetchMemorySummary, { interval: 30000 })
  const { data: logsData } = usePolling(() => fetchLogs(12), { interval: 10000 })
  const { data: roleTemplatesData } = usePolling(fetchRoleTemplates, { interval: 30000 })
  const { data: artifactsData, refresh: refreshArtifacts } = usePolling(fetchArtifacts, { interval: 15000 })
  const { data: metricsData } = usePolling(fetchWorkflowMetrics, { interval: 15000 })
  const [artifactBusy, setArtifactBusy] = useState<string | null>(null)
  const { sessions, currentSessionId, createSession, selectSession, renameSession, archiveSession, restoreSession, deleteSession } = useChatSessions()
  const {
    drafts,
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
  } = useTaskDrafts()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null)
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({})
  const [executingDraftId, setExecutingDraftId] = useState<string | null>(null)
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

  const tasks = (taskData ?? []).slice().reverse().slice(0, 12)
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
  const artifacts: ArtifactFile[] = artifactsData ?? []
  const workflowMetrics: WorkflowMetrics | null = metricsData ?? null
  const latestTask = tasks[0] ?? null
  const livePulse = (logsData?.items ?? []).some((entry) => {
    const eventType = String(entry.event_type ?? '').toLowerCase()
    return isRecentIso(entry.timestamp) && (eventType.includes('task_') || eventType.includes('workflow_'))
  })
  const anchorMeta = useMemo(() => {
    if (activeTab === 'workspaces') return { title: 'Workspace Anchor', subtitle: `${workspaces.length} workspace profiles`, hint: currentWorkspaceName }
    if (activeTab === 'chat') return { title: 'Conversation Anchor', subtitle: `${recentSessions.length} active threads`, hint: currentWorkspaceName }
    if (activeTab === 'tasks') return { title: 'Execution Anchor', subtitle: `${tasks.length} tracked tasks`, hint: latestTask?.status ?? 'idle' }
    if (activeTab === 'files') return { title: 'File Anchor', subtitle: `${treeData?.length ?? 0} root nodes`, hint: currentWorkspaceName }
    if (activeTab === 'skills') return { title: 'Skill Anchor', subtitle: `${installedSkills.length} installed`, hint: currentWorkspaceName }
    if (activeTab === 'tools') return { title: 'Tool Anchor', subtitle: `${(toolsData ?? []).length} discovered`, hint: currentWorkspaceName }
    if (activeTab === 'memory') return { title: 'Memory Anchor', subtitle: `${memoryData?.working_entries ?? 0} working entries`, hint: 'runtime memory summary' }
    if (activeTab === 'logs') return { title: 'Log Anchor', subtitle: `${logsData?.items?.length ?? 0} recent events`, hint: 'live telemetry feed' }
    if (activeTab === 'scheduler') return { title: 'Scheduler Anchor', subtitle: 'Job timeline and heartbeat', hint: 'scheduler panel' }
    return { title: 'Settings Anchor', subtitle: 'Runtime and provider controls', hint: 'configuration' }
  }, [activeTab, workspaces.length, currentWorkspaceName, recentSessions.length, tasks.length, latestTask?.status, treeData?.length, installedSkills.length, toolsData, memoryData?.working_entries, logsData?.items?.length])

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
    void fetchTaskDetail(selectedTaskId)
      .then((task) => {
        if (mounted) setSelectedTask(task)
      })
      .catch(() => {
        if (mounted) setSelectedTask(null)
      })
    return () => {
      mounted = false
    }
  }, [selectedTaskId])

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

  async function executeDraft(draft: TaskDraft, startAt = 0) {
    const { id: draftId, steps } = draft
    const filteredSteps = steps.map((s) => s.trim()).filter(Boolean)
    if (filteredSteps.length === 0) {
      setExecutionResult(draftId, 'Cannot run draft: no non-empty steps.')
      return
    }

    setExecutingDraftId(draftId)
    if (!draft.execution || draft.execution.steps.length !== filteredSteps.length || startAt <= 0) {
      startExecution(draftId, filteredSteps)
    } else {
      resetExecutionFromStep(draftId, startAt)
    }

    const outputs: string[] = (draft.execution?.steps ?? [])
      .slice(0, startAt)
      .filter((s) => s.status === 'done' || s.status === 'skipped')
      .map((s) => s.output ?? '')
      .filter(Boolean)

    try {
      const cfg = await fetchConfig()
      const backend = typeof cfg['model.default_backend'] === 'string' ? String(cfg['model.default_backend']) : undefined

      for (let i = startAt; i < filteredSteps.length; i += 1) {
        const step = filteredSteps[i]
        updateExecutionStep(draftId, i, 'running')
        const contextBlock = outputs.length > 0
          ? `\n\nPrevious completed step outputs:\n${outputs.map((o, idx) => `${idx + 1}. ${o}`).join('\n')}`
          : ''
        const prompt = `You are executing a task checklist. Complete step ${i + 1}/${filteredSteps.length}: ${step}${contextBlock}`
        try {
          const res = await sendChat({ prompt, ...(backend ? { model_backend: backend } : {}) })
          const output = (res.response ?? '').slice(0, 400)
          outputs.push(output)
          updateExecutionStep(draftId, i, 'done', output)
        } catch (stepError) {
          const stepErr = stepError instanceof Error ? stepError.message : String(stepError)
          updateExecutionStep(draftId, i, 'error', stepErr)
          throw stepError
        }
      }

      setExecutionResult(draftId, outputs.join('\n').slice(0, 1000))
    } catch (e) {
      setExecutionResult(draftId, e instanceof Error ? e.message : String(e))
    } finally {
      finishExecution(draftId)
      setExecutingDraftId(null)
    }
  }

  async function retryExecutionStep(draft: TaskDraft, index: number) {
    if (executingDraftId) return
    await executeDraft(draft, index)
  }

  function skipExecutionStep(draftId: string, index: number, instruction: string) {
    updateExecutionStep(draftId, index, 'skipped', `Skipped: ${instruction}`)
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
          <p className={styles.anchorSubtitle}>{anchorMeta.subtitle}</p>
          <div className={styles.anchorMetaRow}>
            <span className={`badge ${livePulse ? 'badge-warn' : 'badge-dim'}`}>{livePulse ? 'active now' : 'idle'}</span>
            <span className={styles.anchorHint}>{anchorMeta.hint}</span>
          </div>
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
            <p className={styles.hint}>Global tasks (not workspace scoped)</p>
            {drafts.length > 0 && (
              <>
                <p className={styles.hint}>Promoted task drafts</p>
                {drafts.slice(0, 10).map((draft) => (
                  <div key={draft.id} className={styles.detailCard}>
                    <input
                      className={styles.stepInput}
                      value={draft.title}
                      onChange={(e) => setDraftTitle(draft.id, e.target.value)}
                    />
                    <p className={styles.rowMeta}>{draft.steps.length} steps</p>
                    <div className={styles.stepsList}>
                      {draft.steps.map((step, index) => (
                        <div key={`${draft.id}-step-${index}`} className={styles.stepRow}>
                          <input
                            className={styles.stepInput}
                            value={step}
                            onChange={(e) => setDraftStep(draft.id, index, e.target.value)}
                          />
                          <div className={styles.rowActions}>
                            <button className={styles.actionBtn} onClick={() => moveDraftStep(draft.id, index, -1)} data-tooltip="Move up" aria-label="Move step up">
                              <ArrowUp size={12} />
                            </button>
                            <button className={styles.actionBtn} onClick={() => moveDraftStep(draft.id, index, 1)} data-tooltip="Move down" aria-label="Move step down">
                              <ArrowDown size={12} />
                            </button>
                            <button className={styles.actionBtn} onClick={() => removeDraftStep(draft.id, index)} data-tooltip="Remove step" aria-label="Remove step">
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className={styles.rowActions}>
                      <button className={styles.actionBtn} onClick={() => addDraftStep(draft.id)} data-tooltip="Add step" aria-label="Add step">
                        <Plus size={12} />
                      </button>
                      <button className={styles.actionBtn} onClick={() => void executeDraft(draft)} data-tooltip="Run draft" aria-label="Run draft" disabled={executingDraftId === draft.id}>
                        <Play size={12} />
                      </button>
                      <button className={styles.actionBtn} onClick={() => deleteDraft(draft.id)} data-tooltip="Delete draft" aria-label="Delete draft">
                        <Trash2 size={12} />
                      </button>
                    </div>
                    {draft.execution && (
                      <div className={styles.executionLog}>
                        {draft.execution.steps.map((stepLog, i) => (
                          <div key={`${draft.id}-log-${i}`} className={styles.executionItem}>
                            <span className={`badge ${stepLog.status === 'done' ? 'badge-ok' : stepLog.status === 'error' ? 'badge-error' : stepLog.status === 'running' ? 'badge-warn' : stepLog.status === 'skipped' ? 'badge-dim' : 'badge-dim'}`}>
                              {stepLog.status}
                            </span>
                            <span className={styles.executionText}>{stepLog.instruction}</span>
                            <div className={styles.executionActions}>
                              <button
                                className={styles.actionBtn}
                                onClick={() => void retryExecutionStep(draft, i)}
                                data-tooltip="Retry from this step"
                                aria-label="Retry from this step"
                                disabled={executingDraftId !== null}
                              >
                                <RotateCcw size={12} />
                              </button>
                              <button
                                className={styles.actionBtn}
                                onClick={() => skipExecutionStep(draft.id, i, stepLog.instruction)}
                                data-tooltip="Skip this step"
                                aria-label="Skip this step"
                                disabled={executingDraftId !== null || stepLog.status === 'done' || stepLog.status === 'skipped'}
                              >
                                <ChevronRight size={12} />
                              </button>
                            </div>
                            {stepLog.output && <p className={styles.detailText}>{stepLog.output}</p>}
                          </div>
                        ))}
                      </div>
                    )}
                    {draft.lastResult && <p className={styles.detailText}>{draft.lastResult}</p>}
                  </div>
                ))}
              </>
            )}
            {tasks.length === 0 && <p className={styles.empty}>No tasks yet.</p>}
            {tasks.map((task) => (
              <button
                key={task.task_id}
                className={`${styles.itemRow} ${styles.edgeReactive} ${selectedTaskId === task.task_id ? styles.rowActive : ''} ${task.status === 'running' ? styles.rowHot : ''}`}
                onClick={() => setSelectedTaskId(task.task_id)}
                title={task.description}
                onMouseMove={applyEdgeGlow}
              >
                <span className={styles.rowTitle}>{task.description}</span>
                <span className={`badge ${task.status === 'completed' ? 'badge-ok' : task.status === 'failed' ? 'badge-error' : 'badge-warn'}`}>
                  {task.status}
                </span>
              </button>
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
            <p className={styles.hint}>Scheduler panel</p>
            <p className={styles.empty}>Scheduler detail can be added next; chat remains available in the center.</p>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className={styles.list}>
            <p className={styles.hint}>Settings are open in the center pane.</p>
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
