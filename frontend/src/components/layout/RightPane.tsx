import { useState } from 'react'
import {
  Activity,
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
import { CurrentRunTab } from './right/CurrentRunTab'
import { HealthTab } from './right/HealthTab'
import { SkillsTab } from './right/SkillsTab'
import { ToolsTab } from './right/ToolsTab'
import { MemoryTab } from './right/MemoryTab'
import { LogsTab } from './right/LogsTab'

const TABS: { id: RightTab; label: string; Icon: React.FC<{ size?: number }> }[] = [
  { id: 'run',    label: 'Run',    Icon: Activity },
  { id: 'agent',  label: 'Agent',  Icon: Bot },
  { id: 'skills', label: 'Skills', Icon: Zap },
  { id: 'tools',  label: 'Tools',  Icon: Wrench },
  { id: 'memory', label: 'Memory', Icon: Brain },
  { id: 'logs',   label: 'Logs',   Icon: ScrollText },
  { id: 'health', label: 'Health', Icon: HeartPulse },
]

export function RightPane() {
  const [active, setActive] = useState<RightTab>('run')

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
        {active === 'run' && <CurrentRunTab />}
        {active === 'agent' && <AgentTab />}
        {active === 'skills' && <SkillsTab />}
        {active === 'tools' && <ToolsTab />}
        {active === 'memory' && <MemoryTab />}
        {active === 'logs' && <LogsTab />}
        {active === 'health' && <HealthTab />}
      </div>
    </div>
  )
}
