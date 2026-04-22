import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Palette } from 'lucide-react'
import { useTheme, type Theme } from '../../contexts/ThemeContext'
import { usePolling } from '../../hooks/usePolling'
import { fetchConfig, fetchStatus } from '../../api/client'
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
  const { data, error } = usePolling(fetchStatus, { interval: 8000 })
  const { data: cfg } = usePolling(fetchConfig, { interval: 8000 })

  const backend = String(cfg?.['model.default_backend'] ?? data?.default_model_backend ?? 'unknown')
  const checking = !data && !error
  const connected = checking ? false : (data?.model_connected ?? (backend === 'local_stub'))
  const statusLabel = checking ? 'checking' : (connected ? 'connected' : 'disconnected')
  const statusClass = checking ? 'badge-dim' : (connected ? 'badge-ok' : 'badge-error')
  const backendUp = checking ? false : Boolean(data?.ok && !error)
  const backendLabel = checking ? 'checking' : (backendUp ? 'up' : 'down')
  const backendClass = checking ? 'badge-dim' : (backendUp ? 'badge-ok' : 'badge-error')

  return (
    <div className={styles.root}>
      <div className={styles.left}>
        <button className={styles.iconBtn} onClick={onToggleLeft} title={leftCollapsed ? 'Show sidebar' : 'Hide sidebar'}>
          {leftCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
        <span className={styles.title}>TitanShift</span>
      </div>

      <div className={styles.right}>
        <div className={styles.modelStatus} title={error ?? 'Backend API status'}>
          <span className={styles.modelLabel}>Backend</span>
          <span className={`badge ${backendClass}`}>{backendLabel}</span>
        </div>

        <div className={styles.modelStatus} title={error ?? data?.model_connection_reason ?? 'Model connection status'}>
          <span className={styles.modelLabel}>Model</span>
          <span className={`badge ${statusClass}`}>{statusLabel}</span>
          <span className={`${styles.modelBackend} font-mono`}>{backend}</span>
        </div>

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
