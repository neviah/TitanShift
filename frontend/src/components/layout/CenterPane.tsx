import type { NavTab } from '../../types/nav'
import { ChatView } from '../../views/ChatView'
import { SkillsView } from '../../views/SkillsView'
import { PlaceholderView } from '../../views/PlaceholderView'
import { MarketOverview } from '../../views/dashboard/MarketOverview'
import { IngestionOverview } from '../../views/dashboard/IngestionOverview'
import styles from './CenterPane.module.css'

interface CenterPaneProps {
  activeTab: NavTab
}

export function CenterPane({ activeTab }: CenterPaneProps) {
  return (
    <div className={styles.root}>
      {activeTab === 'chat' && <ChatView />}
      {activeTab === 'skills' && <SkillsView />}
      {activeTab === 'tasks' && <PlaceholderView label="Tasks" />}
      {activeTab === 'scheduler' && <PlaceholderView label="Scheduler" />}
      {activeTab === 'files' && <PlaceholderView label="Files" />}
      {activeTab === 'tools' && <PlaceholderView label="Tools" />}
      {activeTab === 'memory' && <PlaceholderView label="Memory" />}
      {activeTab === 'logs' && <PlaceholderView label="Logs" />}
      {activeTab === 'settings' && (
        <div className={styles.settings}>
          <div className={styles.overviews}>
            <MarketOverview />
            <IngestionOverview />
          </div>
        </div>
      )}
    </div>
  )
}
