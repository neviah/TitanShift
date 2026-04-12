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
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'
import { usePolling } from '../../hooks/usePolling'
import { fetchMarketList, fetchTasks } from '../../api/client'

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

const CHAT_STORAGE_KEY = 'titanshift-chat-history-v1'

interface LeftPaneProps {
  activeTab: NavTab
  onTabChange: (tab: NavTab) => void
}

export function LeftPane({ activeTab, onTabChange }: LeftPaneProps) {
  const { data: taskData } = usePolling(fetchTasks, { interval: 8000 })
  const { data: skillsData } = usePolling(fetchMarketList, { interval: 30000 })
  const [chatRev, setChatRev] = useState(0)

  useEffect(() => {
    const onChatUpdated = () => setChatRev((v) => v + 1)
    window.addEventListener('titanshift:chat-updated', onChatUpdated)
    return () => {
      window.removeEventListener('titanshift:chat-updated', onChatUpdated)
    }
  }, [])

  const recentChats = useMemo(() => {
    try {
      const raw = localStorage.getItem(CHAT_STORAGE_KEY)
      if (!raw) return [] as string[]
      const parsed = JSON.parse(raw) as Array<{ role?: string; text?: string }>
      if (!Array.isArray(parsed)) return [] as string[]
      return parsed
        .filter((m) => m?.role === 'user' && typeof m?.text === 'string')
        .map((m) => (m.text as string).trim())
        .filter(Boolean)
        .slice(-8)
        .reverse()
    } catch {
      return [] as string[]
    }
  }, [activeTab, chatRev])

  const tasks = (taskData ?? []).slice().reverse().slice(0, 12)
  const installedSkills = (skillsData ?? []).filter((s) => s.installed).slice(0, 12)

  function handleNewChat() {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify([]))
    window.dispatchEvent(new Event('titanshift:new-chat'))
    onTabChange('chat')
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
              {recentChats.length === 0 && <p className={styles.empty}>No previous chats yet.</p>}
              {recentChats.map((msg, idx) => (
                <button key={`${msg}-${idx}`} className={styles.row} title={msg} onClick={() => onTabChange('chat')}>
                  {msg}
                </button>
              ))}
            </div>
          </>
        )}

        {activeTab === 'tasks' && (
          <div className={styles.list}>
            {tasks.length === 0 && <p className={styles.empty}>No tasks yet.</p>}
            {tasks.map((task) => (
              <div key={task.task_id} className={styles.itemRow}>
                <span className={styles.rowTitle}>{task.description}</span>
                <span className={`badge ${task.status === 'completed' ? 'badge-ok' : task.status === 'failed' ? 'badge-error' : 'badge-warn'}`}>
                  {task.status}
                </span>
              </div>
            ))}
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

        {(activeTab === 'files' || activeTab === 'scheduler' || activeTab === 'tools' || activeTab === 'memory' || activeTab === 'logs') && (
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
