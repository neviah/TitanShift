import type { NavTab } from '../../types/nav'
import { ChatView } from '../../views/ChatView'
import { SkillsView } from '../../views/SkillsView'
import { SettingsView } from '../../views/SettingsView'
import { PlaceholderView } from '../../views/PlaceholderView'
import styles from './CenterPane.module.css'

interface CenterPaneProps {
  activeTab: NavTab
}

export function CenterPane({ activeTab }: CenterPaneProps) {
  return (
    <div className={styles.root}>
      {activeTab === 'chat'      && <ChatView />}
      {activeTab === 'skills'    && <SkillsView />}
      {activeTab === 'settings'  && <SettingsView />}
      {activeTab === 'tasks'     && <PlaceholderView label="Tasks" />}
      {activeTab === 'scheduler' && <PlaceholderView label="Scheduler" />}
      {activeTab === 'files'     && <PlaceholderView label="Files" />}
      {activeTab === 'tools'     && <PlaceholderView label="Tools" />}
      {activeTab === 'memory'    && <PlaceholderView label="Memory" />}
      {activeTab === 'logs'      && <PlaceholderView label="Logs" />}
    </div>
  )
}
