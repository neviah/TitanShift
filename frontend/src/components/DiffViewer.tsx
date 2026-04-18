import styles from './DiffViewer.module.css'

interface DiffViewerProps {
  /** Unified diff text (output of patch_file or apply_wiring) */
  diff?: string
  /** If diff not provided, show before/after strings directly */
  before?: string
  after?: string
  title?: string
  /** Language hint for code colour class (e.g. 'python', 'tsx') */
  lang?: string
}

interface DiffLine {
  kind: 'add' | 'remove' | 'context' | 'header'
  text: string
  lineNumLeft: number | null
  lineNumRight: number | null
}

function parseUnifiedDiff(diff: string): DiffLine[] {
  const lines = diff.split('\n')
  const out: DiffLine[] = []
  let leftLine = 0
  let rightLine = 0

  for (const raw of lines) {
    if (raw.startsWith('---') || raw.startsWith('+++')) {
      out.push({ kind: 'header', text: raw, lineNumLeft: null, lineNumRight: null })
      continue
    }
    if (raw.startsWith('@@')) {
      // Parse @@ -L,S +L,S @@ header
      const m = raw.match(/@@ -(\d+)(?:,\d+)? \+(\d+)/)
      if (m) {
        leftLine = parseInt(m[1], 10) - 1
        rightLine = parseInt(m[2], 10) - 1
      }
      out.push({ kind: 'header', text: raw, lineNumLeft: null, lineNumRight: null })
      continue
    }
    if (raw.startsWith('+')) {
      rightLine++
      out.push({ kind: 'add', text: raw.slice(1), lineNumLeft: null, lineNumRight: rightLine })
    } else if (raw.startsWith('-')) {
      leftLine++
      out.push({ kind: 'remove', text: raw.slice(1), lineNumLeft: leftLine, lineNumRight: null })
    } else {
      leftLine++
      rightLine++
      out.push({ kind: 'context', text: raw.slice(1), lineNumLeft: leftLine, lineNumRight: rightLine })
    }
  }
  return out
}

function buildSideBySideRows(lines: DiffLine[]): Array<{ left: DiffLine | null; right: DiffLine | null }> {
  const rows: Array<{ left: DiffLine | null; right: DiffLine | null }> = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.kind === 'header') {
      rows.push({ left: line, right: line })
      i++
      continue
    }
    if (line.kind === 'remove') {
      // Peek ahead for a matching add
      const nextAdd = lines[i + 1]?.kind === 'add' ? lines[i + 1] : null
      rows.push({ left: line, right: nextAdd })
      i += nextAdd ? 2 : 1
      continue
    }
    if (line.kind === 'add') {
      rows.push({ left: null, right: line })
      i++
      continue
    }
    // context
    rows.push({ left: line, right: line })
    i++
  }
  return rows
}

function renderPlainSideBySide(before: string, after: string): Array<{ left: DiffLine | null; right: DiffLine | null }> {
  const beforeLines = before.split('\n')
  const afterLines = after.split('\n')
  const max = Math.max(beforeLines.length, afterLines.length)
  return Array.from({ length: max }, (_, i) => ({
    left: i < beforeLines.length ? { kind: 'remove' as const, text: beforeLines[i], lineNumLeft: i + 1, lineNumRight: null } : null,
    right: i < afterLines.length ? { kind: 'add' as const, text: afterLines[i], lineNumLeft: null, lineNumRight: i + 1 } : null,
  }))
}

function LineNumCell({ n }: { n: number | null }) {
  return <span className={styles.lineNum}>{n ?? ''}</span>
}

export function DiffViewer({ diff, before, after, title, lang }: DiffViewerProps) {
  let rows: Array<{ left: DiffLine | null; right: DiffLine | null }> = []

  if (diff && diff.trim()) {
    const parsed = parseUnifiedDiff(diff)
    rows = buildSideBySideRows(parsed)
  } else if (before !== undefined && after !== undefined) {
    rows = renderPlainSideBySide(before, after)
  }

  if (rows.length === 0) return null

  return (
    <div className={styles.root}>
      {title && <div className={styles.header}>{title}</div>}
      <div className={styles.tableWrap}>
        <table className={`${styles.table} ${lang ? styles[`lang_${lang}`] : ''}`}>
          <colgroup>
            <col className={styles.colNum} />
            <col className={styles.colCode} />
            <col className={styles.colDivider} />
            <col className={styles.colNum} />
            <col className={styles.colCode} />
          </colgroup>
          <tbody>
            {rows.map((row, i) => {
              if (row.left?.kind === 'header' || row.right?.kind === 'header') {
                const text = (row.left ?? row.right)!.text
                return (
                  <tr key={i} className={styles.rowHeader}>
                    <td colSpan={5} className={styles.cellHeader}>{text}</td>
                  </tr>
                )
              }
              return (
                <tr key={i} className={styles.row}>
                  <td className={`${styles.cellNum} ${row.left?.kind === 'remove' ? styles.cellRemove : ''}`}>
                    <LineNumCell n={row.left?.lineNumLeft ?? null} />
                  </td>
                  <td className={`${styles.cellCode} ${row.left?.kind === 'remove' ? styles.cellRemove : ''}`}>
                    {row.left ? <code>{row.left.text}</code> : null}
                  </td>
                  <td className={styles.cellDivider} />
                  <td className={`${styles.cellNum} ${row.right?.kind === 'add' ? styles.cellAdd : ''}`}>
                    <LineNumCell n={row.right?.lineNumRight ?? null} />
                  </td>
                  <td className={`${styles.cellCode} ${row.right?.kind === 'add' ? styles.cellAdd : ''}`}>
                    {row.right ? <code>{row.right.text}</code> : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
