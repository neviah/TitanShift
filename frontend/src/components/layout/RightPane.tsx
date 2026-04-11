import { useState } from 'react'
import {
  Bot,
  Zap,
  Wrench,
  Brain,
  ScrollText,
  HeartPulse,
} from 'lucide-react'
import styles from './RightPane.module.css'
import type { RightTab } from '../../types/nav'
import { AgentTab } from './right/AgentTab'
import { HealthTab } from './right/HealthTab'
import { PlaceholderTab } from './right/PlaceholderTab'

const TABS: { id: RightTab; label: string; Icon: React.FC<{ size?: number }> }[] = [
  { id: 'agent',  label: 'Agent',  Icon: Bot },
  { id: 'skills', label: 'Skills', Icon: Zap },
  { id: 'tools',  label: 'Tools',  Icon: Wrench },
  { id: 'memory', label: 'Memory', Icon: Brain },
  { id: 'logs',   label: 'Logs',   Icon: ScrollText },
  { id: 'health', label: 'Health', Icon: HeartPulse },
]

export function RightPane() {
  const [active, setActive] = useState<RightTab>('agent')

  return (
    <div className={styles.root}>
      <div className={styles.tabBar}>
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`${styles.tabBtn} ${active === id ? styles.active : ''}`}
            onClick={() => setActive(id)}
            title={label}
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className={styles.body}>
        {active === 'agent'  && <AgentTab />}
        {active === 'health' && <HealthTab />}
        {active !== 'agent' && active !== 'health' && (
          <PlaceholderTab label={active} />
        )}
      </div>
    </div>
  )
}
