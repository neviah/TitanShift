import { useEffect, useState } from 'react'
import { fetchConfig, updateConfig } from '../api/client'
import { useSchedulerTask } from '../contexts/SchedulerTaskContext'
import styles from './SettingsView.module.css'
import { Save, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react'
import { MarketOverview } from './dashboard/MarketOverview'
import { IngestionOverview } from './dashboard/IngestionOverview'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const BACKENDS = [
  { value: 'local_stub',        label: 'Local Stub (no model)',      group: 'Local' },
  { value: 'lmstudio',          label: 'LM Studio',                   group: 'Local' },
  { value: 'openai_compatible', label: 'OpenAI Compatible (API)', group: 'Cloud' },
]

interface ConfigState {
  'model.default_backend': string
  'model.allow_cloud_adapters'?: boolean
  'model.lmstudio.base_url'?: string
  'model.lmstudio.model'?: string
  'model.lmstudio.timeout_s'?: number
  'model.openai_compatible.base_url'?: string
  'model.openai_compatible.model'?: string
  'model.openai_compatible.api_key'?: string
  'model.openai_compatible.timeout_s'?: number
  'orchestrator.enable_subagents': boolean
  'orchestrator.superpowered_mode.disable_run_timeout'?: boolean
  'orchestrator.superpowered_mode.run_timeout_seconds'?: number
  'orchestrator.superpowered_mode.disable_budget_timeout'?: boolean
  'tools.allow_network': boolean
  'tools.deny_all_by_default': boolean
  'state_machine.default_budget.max_steps': number
  'state_machine.default_budget.max_tokens': number
  [key: string]: unknown
}

export function SettingsView() {
  const [config, setConfig] = useState<ConfigState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [dirty, setDirty] = useState<Record<string, unknown>>({})
  const { concurrencyMode, setConcurrencyMode } = useSchedulerTask()

  async function loadConfig() {
    setLoading(true)
    try {
      const raw = await fetchConfig()
      setConfig(raw as ConfigState)
      setDirty({})
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadConfig() }, [])

  function patchLocal(key: string, value: unknown) {
    setConfig((prev) => prev ? { ...prev, [key]: value } : prev)
    setDirty((prev) => ({ ...prev, [key]: value }))
    setSaveState('idle')
  }

  async function saveAll() {
    if (Object.keys(dirty).length === 0) return
    setSaveState('saving')
    try {
      for (const [key, value] of Object.entries(dirty)) {
        await updateConfig(key, value)
      }
      setSaveState('saved')
      setDirty({})
      setTimeout(() => setSaveState('idle'), 2000)
    } catch (e) {
      setSaveState('error')
    }
  }

  const hasDirty = Object.keys(dirty).length > 0

  return (
    <div className={styles.root}>
      <div className={styles.topBar}>
        <h2 className={styles.pageTitle}>Settings</h2>
        <div className={styles.topActions}>
          <button className={styles.refreshBtn} onClick={loadConfig} title="Reload from server">
            <RefreshCw size={14} />
          </button>
          {hasDirty && saveState !== 'saving' && (
            <button className={styles.saveBtn} onClick={saveAll}>
              <Save size={14} />
              Save changes
            </button>
          )}
          {saveState === 'saving' && <span className={styles.saveHint}>Saving…</span>}
          {saveState === 'saved' && (
            <span className={`${styles.saveHint} text-ok`}>
              <CheckCircle size={13} /> Saved
            </span>
          )}
          {saveState === 'error' && (
            <span className={`${styles.saveHint} text-error`}>
              <AlertCircle size={13} /> Failed
            </span>
          )}
        </div>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}

      {config && (
        <div className={styles.sections}>

          {/* ── Model Provider ── */}
          <Section title="Model Provider">
            <Field label="Default backend">
              <select
                className={styles.select}
                value={String(config['model.default_backend'] ?? 'local_stub')}
                onChange={(e) => patchLocal('model.default_backend', e.target.value)}
              >
                {['Local', 'Cloud'].map((group) => (
                  <optgroup key={group} label={group}>
                    {BACKENDS.filter((b) => b.group === group).map((b) => (
                      <option key={b.value} value={b.value}>{b.label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Field>

            <Field label="Allow cloud adapters">
              <Toggle
                checked={Boolean(config['model.allow_cloud_adapters'])}
                onChange={(v) => patchLocal('model.allow_cloud_adapters', v)}
              />
            </Field>

            {String(config['model.default_backend'] ?? '') === 'lmstudio' && (
              <>
                <Field label="LM Studio base URL">
                  <input
                    type="text"
                    className={styles.textInput}
                    value={String(config['model.lmstudio.base_url'] ?? 'http://127.0.0.1:1234/v1')}
                    onChange={(e) => patchLocal('model.lmstudio.base_url', e.target.value)}
                    placeholder="http://127.0.0.1:1234/v1"
                  />
                </Field>

                <Field label="LM Studio model id">
                  <input
                    type="text"
                    className={styles.textInput}
                    value={String(config['model.lmstudio.model'] ?? '')}
                    onChange={(e) => patchLocal('model.lmstudio.model', e.target.value)}
                    placeholder="google/gemma-3-4b"
                  />
                </Field>

                <Field label="LM Studio timeout (seconds)">
                  <input
                    type="number"
                    className={styles.numInput}
                    min={1}
                    max={300}
                    value={Number(config['model.lmstudio.timeout_s'] ?? 45)}
                    onChange={(e) => patchLocal('model.lmstudio.timeout_s', Number(e.target.value))}
                  />
                </Field>
              </>
            )}

            {String(config['model.default_backend'] ?? '') === 'openai_compatible' && (
              <>
                <Field label="OpenAI-compatible base URL">
                  <input
                    type="text"
                    className={styles.textInput}
                    value={String(config['model.openai_compatible.base_url'] ?? 'https://openrouter.ai/api/v1')}
                    onChange={(e) => patchLocal('model.openai_compatible.base_url', e.target.value)}
                    placeholder="https://openrouter.ai/api/v1"
                  />
                </Field>

                <Field label="Provider model id">
                  <input
                    type="text"
                    className={styles.textInput}
                    value={String(config['model.openai_compatible.model'] ?? '')}
                    onChange={(e) => patchLocal('model.openai_compatible.model', e.target.value)}
                    placeholder="openai/gpt-4o-mini"
                  />
                </Field>

                <Field label="Provider API key">
                  <input
                    type="password"
                    className={styles.textInput}
                    value={String(config['model.openai_compatible.api_key'] ?? '')}
                    onChange={(e) => patchLocal('model.openai_compatible.api_key', e.target.value)}
                    placeholder="sk-..."
                  />
                </Field>

                <Field label="Provider timeout (seconds)">
                  <input
                    type="number"
                    className={styles.numInput}
                    min={1}
                    max={300}
                    value={Number(config['model.openai_compatible.timeout_s'] ?? 45)}
                    onChange={(e) => patchLocal('model.openai_compatible.timeout_s', Number(e.target.value))}
                  />
                </Field>
              </>
            )}

            <ProviderHint backend={String(config['model.default_backend'] ?? '')} />
          </Section>

          {/* ── Orchestrator ── */}
          <Section title="Orchestrator">
            <Field label="Enable subagents">
              <Toggle
                checked={Boolean(config['orchestrator.enable_subagents'])}
                onChange={(v) => patchLocal('orchestrator.enable_subagents', v)}
              />
            </Field>

            <Field label="Superpowered: remove run timeout">
              <Toggle
                checked={Boolean(config['orchestrator.superpowered_mode.disable_run_timeout'] ?? true)}
                onChange={(v) => patchLocal('orchestrator.superpowered_mode.disable_run_timeout', v)}
              />
            </Field>

            <Field label="Superpowered run timeout (seconds)">
              <input
                type="number"
                className={styles.numInput}
                min={0}
                step={30}
                value={Number(config['orchestrator.superpowered_mode.run_timeout_seconds'] ?? 0)}
                disabled={Boolean(config['orchestrator.superpowered_mode.disable_run_timeout'] ?? true)}
                onChange={(e) => patchLocal('orchestrator.superpowered_mode.run_timeout_seconds', Number(e.target.value))}
              />
            </Field>

            <Field label="Superpowered: remove budget timeout">
              <Toggle
                checked={Boolean(config['orchestrator.superpowered_mode.disable_budget_timeout'] ?? true)}
                onChange={(v) => patchLocal('orchestrator.superpowered_mode.disable_budget_timeout', v)}
              />
            </Field>
            <p className={styles.fieldHint}>
              When enabled, long Superpowered runs are not auto-stopped by timer limits. Use Stop in Chat to cancel manually.
            </p>

          {/* ── Scheduler ── */}
          <Section title="Scheduler">
            <Field label="Concurrency mode">
              <select
                className={styles.select}
                value={concurrencyMode}
                onChange={(e) => setConcurrencyMode(e.target.value as 'single-run' | 'parallel')}
              >
                <option value="single-run">Single-Run (queue new tasks)</option>
                <option value="parallel">Parallel (run tasks concurrently)</option>
              </select>
            </Field>
            <p className={styles.fieldHint}>
              Single-run waits for tasks to complete before running new ones. Parallel allows multiple tasks to run simultaneously.
            </p>
          </Section>
          </Section>

          {/* ── Budget ── */}
          <Section title="Default Budget">
            <Field label="Max steps">
              <input
                type="number"
                className={styles.numInput}
                min={1}
                max={100}
                value={Number(config['state_machine.default_budget.max_steps'] ?? 1)}
                onChange={(e) => patchLocal('state_machine.default_budget.max_steps', Number(e.target.value))}
              />
            </Field>
            <Field label="Max tokens">
              <input
                type="number"
                className={styles.numInput}
                min={256}
                step={256}
                max={128000}
                value={Number(config['state_machine.default_budget.max_tokens'] ?? 8192)}
                onChange={(e) => patchLocal('state_machine.default_budget.max_tokens', Number(e.target.value))}
              />
            </Field>
          </Section>

          {/* ── Tools ── */}
          <Section title="Tools">
            <Field label="Deny all by default">
              <Toggle
                checked={Boolean(config['tools.deny_all_by_default'])}
                onChange={(v) => patchLocal('tools.deny_all_by_default', v)}
              />
            </Field>
            <Field label="Allow network">
              <Toggle
                checked={Boolean(config['tools.allow_network'])}
                onChange={(v) => patchLocal('tools.allow_network', v)}
              />
            </Field>
          </Section>

          {/* ── System Overview ── */}
          <Section title="System Overview">
            <div className={styles.overviewGrid}>
              <MarketOverview />
              <IngestionOverview />
            </div>
          </Section>

        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>{title}</h3>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel}>{label}</label>
      <div className={styles.fieldControl}>{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      className={`${styles.toggle} ${checked ? styles.toggleOn : ''}`}
      onClick={() => onChange(!checked)}
      role="switch"
      aria-checked={checked}
    >
      <span className={styles.toggleThumb} />
    </button>
  )
}

function ProviderHint({ backend }: { backend: string }) {
  const hints: Record<string, string> = {
    lmstudio:   'Connects to LM Studio at http://127.0.0.1:1234/v1 — start LM Studio and load a model first.',
    openai_compatible: 'Uses any OpenAI-compatible API endpoint (OpenRouter, Ollama OpenAI mode, local gateways).',
    local_stub: 'Stub backend — returns canned responses. Good for testing the UI without a real model.',
  }
  const hint = hints[backend]
  if (!hint) return null
  return <p className={styles.providerHint}>{hint}</p>
}
