import {
  Group,
  Panel,
  Separator,
  type Layout,
} from 'react-resizable-panels'
import styles from './TriPane.module.css'
import type { ReactNode } from 'react'

const STORAGE_KEY = 'titanshift-layout'
const DEFAULT_LAYOUT: Layout = { left: 20, center: 54, right: 26 }

function loadLayout(): Layout {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Layout
  } catch {
    // ignore
  }
  return DEFAULT_LAYOUT
}

function saveLayout(layout: Layout) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout))
  } catch {
    // ignore
  }
}

interface TriPaneProps {
  left: ReactNode
  center: ReactNode
  right: ReactNode
  leftCollapsed?: boolean
  rightCollapsed?: boolean
}

export function TriPane({ left, center, right, leftCollapsed = false, rightCollapsed = false }: TriPaneProps) {
  const saved = loadLayout()

  return (
    <Group
      orientation="horizontal"
      defaultLayout={saved}
      onLayoutChanged={saveLayout}
      className={styles.root}
    >
      {!leftCollapsed && (
        <>
          <Panel
            id="left"
            defaultSize={saved.left ?? DEFAULT_LAYOUT.left}
            minSize={8}
            className={styles.pane}
          >
            {left}
          </Panel>
          <Separator className={styles.handle} />
        </>
      )}

      <Panel id="center" defaultSize={leftCollapsed && rightCollapsed ? 100 : (saved.center ?? DEFAULT_LAYOUT.center)} minSize={15} className={styles.pane}>
        {center}
      </Panel>

      {!rightCollapsed && (
        <>
          <Separator className={styles.handle} />
          <Panel
            id="right"
            defaultSize={saved.right ?? DEFAULT_LAYOUT.right}
            minSize={8}
            className={styles.pane}
          >
            {right}
          </Panel>
        </>
      )}
    </Group>
  )
}
