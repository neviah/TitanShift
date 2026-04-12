import { useState } from 'react'
import { ThemeProvider } from './contexts/ThemeContext'
import { ChatSessionsProvider } from './contexts/ChatSessionsContext'
import { TriPane } from './components/layout/TriPane'
import { LeftPane } from './components/layout/LeftPane'
import { CenterPane } from './components/layout/CenterPane'
import { RightPane } from './components/layout/RightPane'
import { TopBar } from './components/layout/TopBar'
import type { NavTab } from './types/nav'
import styles from './App.module.css'

function Shell() {
  const [activeTab, setActiveTab] = useState<NavTab>('chat')
  const [activeLeftSection, setActiveLeftSection] = useState<NavTab>('chat')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  function handleLeftSectionChange(section: NavTab) {
    setActiveLeftSection(section)

    // Settings always owns the center pane. Skills opens market in center.
    // Other sections keep center in chat for side-by-side workflows.
    if (section === 'settings') {
      setActiveTab('settings')
      return
    }
    if (section === 'skills') {
      setActiveTab('skills')
      return
    }
    setActiveTab('chat')
  }

  return (
    <div className={styles.root}>
      <TopBar
        leftCollapsed={leftCollapsed}
        rightCollapsed={rightCollapsed}
        onToggleLeft={() => setLeftCollapsed((v) => !v)}
        onToggleRight={() => setRightCollapsed((v) => !v)}
      />
      <div className={styles.body}>
        <TriPane
          leftCollapsed={leftCollapsed}
          rightCollapsed={rightCollapsed}
          left={<LeftPane activeTab={activeLeftSection} onTabChange={handleLeftSectionChange} />}
          center={<CenterPane activeTab={activeTab} />}
          right={<RightPane />}
        />
      </div>
    </div>
  )
}

function App() {
  return (
    <ThemeProvider>
      <ChatSessionsProvider>
        <Shell />
      </ChatSessionsProvider>
    </ThemeProvider>
  )
}

export default App

