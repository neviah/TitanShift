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
import styles from './LeftPane.module.css'
import type { NavTab } from '../../types/nav'

const TABS: { id: NavTab; label: string; Icon: React.FC<{ size?: number }> }[] = [
  { id: 'chat',      label: 'Chat',      Icon: MessageSquare },
  { id: 'tasks',     label: 'Tasks',     Icon: ListTodo },
  { id: 'scheduler', label: 'Scheduler', Icon: Clock },
  { id: 'files',     label: 'Files',     Icon: FolderOpen },
  { id: 'skills',    label: 'Skills',    Icon: Zap },
  { id: 'tools',     label: 'Tools',     Icon: Wrench },
  { id: 'memory',    label: 'Memory',    Icon: Brain },
  { id: 'logs',      label: 'Logs',      Icon: ScrollText },
  { id: 'settings',  label: 'Settings',  Icon: Settings },
]

interface LeftPaneProps {
  activeTab: NavTab
  onTabChange: (tab: NavTab) => void
}

export function LeftPane({ activeTab, onTabChange }: LeftPaneProps) {
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
            <span className={styles.label}>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}
