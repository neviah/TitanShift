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
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'
import { usePolling } from '../../hooks/usePolling'
import { fetchLogs, fetchMarketList, fetchMemorySummary, fetchTaskDetail, fetchTasks, fetchTools, fetchWorkspaceTree } from '../../api/client'
import { useChatSessions } from '../../contexts/ChatSessionsContext'
import { useWorkspace } from '../../contexts/WorkspaceContext'
import type { TaskDetail, WorkspaceTreeNode } from '../../api/types'

const ACTIVE_SKILLS_KEY = 'titanshift-active-skills-by-workspace-v1'
const ACTIVE_TOOLS_KEY = 'titanshift-active-tools-by-workspace-v1'

const TABS: { id: NavTab; label: string; Icon: React.FC<{ size?: number }> }[] = [
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
  const { currentWorkspaceId, currentWorkspaceName } = useWorkspace()
  const { data: taskData } = usePolling(fetchTasks, { interval: 8000 })
  const { data: skillsData } = usePolling(fetchMarketList, { interval: 30000 })
  const { data: treeData } = usePolling(fetchWorkspaceTree, { interval: 30000 })
  const { data: toolsData } = usePolling(fetchTools, { interval: 30000 })
  const { data: memoryData } = usePolling(fetchMemorySummary, { interval: 30000 })
  const { data: logsData } = usePolling(() => fetchLogs(12), { interval: 10000 })
  const { sessions, currentSessionId, createSession, selectSession, renameSession, archiveSession, restoreSession, deleteSession } = useChatSessions()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null)
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({})
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

  useEffect(() => {
    localStorage.setItem(ACTIVE_SKILLS_KEY, JSON.stringify(activeSkillsByWorkspace))
  }, [activeSkillsByWorkspace])

  useEffect(() => {
    localStorage.setItem(ACTIVE_TOOLS_KEY, JSON.stringify(activeToolsByWorkspace))
  }, [activeToolsByWorkspace])

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
        {activeTab === 'chat' && (
          <>
            <button className={styles.newChatBtn} onClick={handleNewChat}>New Chat</button>
            <div className={styles.list}>
              {recentSessions.length === 0 && <p className={styles.empty}>No previous chats yet.</p>}
              {recentSessions.map((session) => (
                <div key={session.id} className={`${styles.row} ${currentSessionId === session.id ? styles.rowActive : ''}`}>
                  <button
                    className={styles.rowMain}
                    title={session.title}
                    onClick={() => {
                      selectSession(session.id)
                      onTabChange('chat')
                    }}
                  >
                    <span className={styles.rowTitle}>{session.title}</span>
                    <span className={styles.rowMeta}>{session.messages.length} msgs</span>
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
                  <p className={styles.hint}>Archived</p>
                  {archivedSessions.map((session) => (
                    <div key={session.id} className={styles.row}>
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
            {tasks.length === 0 && <p className={styles.empty}>No tasks yet.</p>}
            {tasks.map((task) => (
              <button
                key={task.task_id}
                className={`${styles.itemRow} ${selectedTaskId === task.task_id ? styles.rowActive : ''}`}
                onClick={() => setSelectedTaskId(task.task_id)}
                title={task.description}
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
                {selectedTask.error && <p className={`${styles.detailText} text-error`}>{selectedTask.error}</p>}
                {typeof selectedTask.output?.response === 'string' && selectedTask.output.response.length > 0 && (
                  <p className={styles.detailText}>{selectedTask.output.response}</p>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'files' && (
          <div className={styles.list}>
            <p className={styles.hint}>Workspace tree</p>
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
