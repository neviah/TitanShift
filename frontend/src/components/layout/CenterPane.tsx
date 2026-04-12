import type { NavTab } from '../../types/nav'
import { ChatView } from '../../views/ChatView'
import { FileView } from '../../views/FileView'
import { SkillsView } from '../../views/SkillsView'
import { SettingsView } from '../../views/SettingsView'
import { PlaceholderView } from '../../views/PlaceholderView'
import { ModuleBackdrop } from './ModuleBackdrop'
import styles from './CenterPane.module.css'

interface CenterPaneProps {
  activeTab: NavTab
  selectedFilePath: string | null
}

export function CenterPane({ activeTab, selectedFilePath }: CenterPaneProps) {
  return (
    <div className={styles.root}>
      <ModuleBackdrop />
      <div className={styles.content}>
        {activeTab === 'chat' && <ChatView />}
        {activeTab === 'skills' && <SkillsView />}
        {activeTab === 'settings' && <SettingsView />}
        {activeTab === 'tasks' && <PlaceholderView label="Tasks" />}
        {activeTab === 'scheduler' && <PlaceholderView label="Scheduler" />}
        {activeTab === 'files' && <FileView selectedFilePath={selectedFilePath} />}
        {activeTab === 'tools' && <PlaceholderView label="Tools" />}
        {activeTab === 'memory' && <PlaceholderView label="Memory" />}
        {activeTab === 'logs' && <PlaceholderView label="Logs" />}
      </div>
    </div>
  )
}
