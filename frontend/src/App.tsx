import { useState } from 'react'
import { ThemeProvider } from './contexts/ThemeContext'
import { ChatSessionsProvider } from './contexts/ChatSessionsContext'
import { WorkspaceProvider } from './contexts/WorkspaceContext'
import { TaskDraftsProvider } from './contexts/TaskDraftsContext'
import { SchedulerTaskProvider } from './contexts/SchedulerTaskContext'
import { ToastProvider } from './contexts/ToastContext'
import { TriPane } from './components/layout/TriPane'
import { LeftPane } from './components/layout/LeftPane'
import { CenterPane } from './components/layout/CenterPane'
import { RightPane } from './components/layout/RightPane'
import { TopBar } from './components/layout/TopBar'
import { HeartbeatTrail } from './components/layout/HeartbeatTrail'
import { ToastContainer } from './components/layout/ToastContainer'
import type { NavTab } from './types/nav'
import styles from './App.module.css'

function Shell() {
  const [activeTab, setActiveTab] = useState<NavTab>('chat')
  const [activeLeftSection, setActiveLeftSection] = useState<NavTab>('chat')
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  function handleLeftSectionChange(section: NavTab) {
    setActiveLeftSection(section)

    // Some tabs intentionally own the center pane.
    if (section === 'settings' || section === 'skills' || section === 'scheduler') {
      setActiveTab(section)
      return
    }

    // Other sections keep center in chat for side-by-side workflows.
    setActiveTab('chat')
  }

  function handleOpenFile(path: string) {
    setActiveLeftSection('files')
    setSelectedFilePath(path)
    setActiveTab('files')
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
        <HeartbeatTrail />
        <TriPane
          leftCollapsed={leftCollapsed}
          rightCollapsed={rightCollapsed}
          left={<LeftPane activeTab={activeLeftSection} onTabChange={handleLeftSectionChange} onOpenFile={handleOpenFile} selectedFilePath={selectedFilePath} />}
          center={<CenterPane activeTab={activeTab} selectedFilePath={selectedFilePath} />}
          right={<RightPane />}
        />
      </div>
      import { useEffect } from 'react'
    </div>
  )
        // Pre-load config on startup so settings persist
        useEffect(() => {
          void (async () => {
            try {
              await fetchConfig()
            } catch {
              // Continue anyway
            }
          })()
        }, [])
}

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <WorkspaceProvider>
          <SchedulerTaskProvider>
            <ChatSessionsProvider>
              <TaskDraftsProvider>
                <Shell />
                <ToastContainer />
              </TaskDraftsProvider>
            </ChatSessionsProvider>
          </SchedulerTaskProvider>
        </WorkspaceProvider>
      </ToastProvider>
    </ThemeProvider>
  )
}

export default App

