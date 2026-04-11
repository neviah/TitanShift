import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Palette } from 'lucide-react'
import { useTheme, type Theme } from '../../contexts/ThemeContext'
import styles from './TopBar.module.css'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'dark',     label: 'Dark' },
  { value: 'light',    label: 'Light' },
  { value: 'alt-dark', label: 'Alt Dark' },
  { value: 'system',   label: 'System' },
]

interface TopBarProps {
  leftCollapsed: boolean
  rightCollapsed: boolean
  onToggleLeft: () => void
  onToggleRight: () => void
}

export function TopBar({ leftCollapsed, rightCollapsed, onToggleLeft, onToggleRight }: TopBarProps) {
  const { theme, setTheme } = useTheme()

  return (
    <div className={styles.root}>
      <div className={styles.left}>
        <button className={styles.iconBtn} onClick={onToggleLeft} title={leftCollapsed ? 'Show sidebar' : 'Hide sidebar'}>
          {leftCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
        <span className={styles.title}>TitanShift</span>
      </div>

      <div className={styles.right}>
        <div className={styles.themePicker}>
          <Palette size={14} className={styles.paletteIcon} />
          <select
            className={styles.themeSelect}
            value={theme}
            onChange={(e) => setTheme(e.target.value as Theme)}
            title="Theme"
          >
            {THEMES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        <button className={styles.iconBtn} onClick={onToggleRight} title={rightCollapsed ? 'Show panel' : 'Hide panel'}>
          {rightCollapsed ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
        </button>
      </div>
    </div>
  )
}
