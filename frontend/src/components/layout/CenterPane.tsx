import type { NavTab } from '../../types/nav'
import { ChatView } from '../../views/ChatView'
import { FileView } from '../../views/FileView'
import { SettingsView } from '../../views/SettingsView'
import { KeyManagementView } from '../../views/KeyManagementView'
import { SchedulerView } from '../../views/SchedulerView'
import { TasksView } from '../../views/TasksView'
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
        {/* ChatView stays always mounted so sending state survives tab switches */}
        <div className={activeTab === 'chat' ? styles.viewWrapper : styles.viewHidden}>
          <ChatView />
        </div>
        {activeTab === 'settings' && <SettingsView />}
        {activeTab === 'keys' && <KeyManagementView />}
        {activeTab === 'tasks' && <TasksView />}
        {activeTab === 'scheduler' && <SchedulerView />}
        {activeTab === 'files' && <FileView selectedFilePath={selectedFilePath} />}
        {activeTab === 'tools' && <PlaceholderView label="Tools" />}
        {activeTab === 'memory' && <PlaceholderView label="Memory" />}
        {activeTab === 'logs' && <PlaceholderView label="Logs" />}
      </div>
    </div>
  )
}
