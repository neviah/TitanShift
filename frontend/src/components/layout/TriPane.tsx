import {
  Group,
  Panel,
  Separator,
} from 'react-resizable-panels'
import styles from './TriPane.module.css'
import type { ReactNode } from 'react'

interface TriPaneProps {
  left: ReactNode
  center: ReactNode
  right: ReactNode
  leftCollapsed?: boolean
  rightCollapsed?: boolean
}

export function TriPane({ left, center, right, leftCollapsed = false, rightCollapsed = false }: TriPaneProps) {
  return (
    <Group orientation="horizontal" className={styles.root}>
      {!leftCollapsed && (
        <>
          <Panel
            id="left"
            defaultSize={20}
            minSize={8}
            className={styles.pane}
          >
            {left}
          </Panel>
          <Separator className={styles.handle} />
        </>
      )}

      <Panel id="center" defaultSize={leftCollapsed && rightCollapsed ? 100 : 54} minSize={15} className={styles.pane}>
        {center}
      </Panel>

      {!rightCollapsed && (
        <>
          <Separator className={styles.handle} />
          <Panel
            id="right"
            defaultSize={26}
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
