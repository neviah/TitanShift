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
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'
import { usePolling } from '../../hooks/usePolling'
import { fetchMarketList, fetchTaskDetail, fetchTasks, fetchWorkspaceTree } from '../../api/client'
import { useChatSessions } from '../../contexts/ChatSessionsContext'
import type { TaskDetail, WorkspaceTreeNode } from '../../api/types'

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
}

export function LeftPane({ activeTab, onTabChange }: LeftPaneProps) {
  const { data: taskData } = usePolling(fetchTasks, { interval: 8000 })
  const { data: skillsData } = usePolling(fetchMarketList, { interval: 30000 })
  const { data: treeData } = usePolling(fetchWorkspaceTree, { interval: 30000 })
  const { sessions, currentSessionId, createSession, selectSession } = useChatSessions()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null)
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({})

  const tasks = (taskData ?? []).slice().reverse().slice(0, 12)
  const installedSkills = (skillsData ?? []).filter((s) => s.installed).slice(0, 12)
  const recentSessions = useMemo(
    () => sessions.slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 12),
    [sessions],
  )

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
            title={label}
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
                <button
                  key={session.id}
                  className={`${styles.row} ${currentSessionId === session.id ? styles.rowActive : ''}`}
                  title={session.title}
                  onClick={() => {
                    selectSession(session.id)
                    onTabChange('chat')
                  }}
                >
                  <span className={styles.rowTitle}>{session.title}</span>
                  <span className={styles.rowMeta}>{session.messages.length} msgs</span>
                </button>
              ))}
            </div>
          </>
        )}

        {activeTab === 'tasks' && (
          <div className={styles.list}>
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
                  <TreeNode key={node.path} node={node} expandedPaths={expandedPaths} onToggle={togglePath} />
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'skills' && (
          <div className={styles.list}>
            <p className={styles.hint}>Installed skills</p>
            {installedSkills.length === 0 && <p className={styles.empty}>No installed skills yet.</p>}
            {installedSkills.map((skill) => (
              <div key={skill.id} className={styles.itemRow}>
                <span className={styles.rowTitle}>{skill.name}</span>
                <span className="badge badge-ok">installed</span>
              </div>
            ))}
            <p className={styles.hint}>Marketplace is shown in the center pane.</p>
          </div>
        )}

        {(activeTab === 'scheduler' || activeTab === 'tools' || activeTab === 'memory' || activeTab === 'logs') && (
          <div className={styles.list}>
            <p className={styles.hint}>Context panel for {activeTab}.</p>
            <p className={styles.empty}>Select {activeTab} to keep this side panel visible while you continue chatting in the center.</p>
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
          title="Settings"
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
  depth = 0,
}: {
  node: WorkspaceTreeNode
  expandedPaths: Record<string, boolean>
  onToggle: (path: string) => void
  depth?: number
}) {
  const isOpen = expandedPaths[node.path] ?? depth < 1

  if (!node.is_dir) {
    return (
      <div className={styles.treeRow} style={{ paddingLeft: `${depth * 14 + 6}px` }} title={node.path}>
        <FileText size={13} className={styles.treeIcon} />
        <span className={styles.treeLabel}>{node.name}</span>
      </div>
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
        <TreeNode key={child.path} node={child} expandedPaths={expandedPaths} onToggle={onToggle} depth={depth + 1} />
      ))}
    </div>
  )
}
