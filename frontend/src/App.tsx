import { useState } from 'react'
import { ThemeProvider } from './contexts/ThemeContext'
import { TriPane } from './components/layout/TriPane'
import { LeftPane } from './components/layout/LeftPane'
import { CenterPane } from './components/layout/CenterPane'
import { RightPane } from './components/layout/RightPane'
import { TopBar } from './components/layout/TopBar'
import type { NavTab } from './types/nav'
import styles from './App.module.css'

function Shell() {
  const [activeTab, setActiveTab] = useState<NavTab>('chat')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

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
          left={<LeftPane activeTab={activeTab} onTabChange={setActiveTab} />}
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
      <Shell />
    </ThemeProvider>
  )
}

export default App

