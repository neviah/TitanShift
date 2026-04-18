import { useCallback, useEffect, useState } from 'react'
import { Plus, RefreshCw, Trash2, ChevronDown, ChevronRight, Copy, Check, AlertTriangle, Key } from 'lucide-react'
import { listApiKeys, createApiKey, revokeApiKey, fetchApiKeyEvents } from '../api/client'
import type { ApiKeyRecord, ApiKeyEventRecord } from '../api/types'
import styles from './KeyManagementView.module.css'

// ---- Helpers ----------------------------------------------------------------

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

function statusLabel(key: ApiKeyRecord): { label: string; variant: 'active' | 'revoked' | 'expired' } {
  if (key.revoked_at) return { label: 'Revoked', variant: 'revoked' }
  if (key.expires_at && new Date(key.expires_at) < new Date()) return { label: 'Expired', variant: 'expired' }
  return { label: 'Active', variant: 'active' }
}

// ---- Create Key Modal -------------------------------------------------------

interface CreateKeyModalProps {
  onClose: () => void
  onCreate: (description: string, scope: 'read' | 'admin', expiresAt: string | null) => Promise<void>
  creating: boolean
}

function CreateKeyModal({ onClose, onCreate, creating }: CreateKeyModalProps) {
  const [description, setDescription] = useState('')
  const [scope, setScope] = useState<'read' | 'admin'>('read')
  const [expiryEnabled, setExpiryEnabled] = useState(false)
  const [expiryDate, setExpiryDate] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const expiresAt = expiryEnabled && expiryDate ? new Date(expiryDate).toISOString() : null
    void onCreate(description, scope, expiresAt)
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h3 className={styles.modalTitle}>
          <Key size={15} />
          Create API Key
        </h3>
        <form onSubmit={handleSubmit} className={styles.form}>
          <label className={styles.formLabel}>
            Description
            <input
              className={styles.formInput}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. CI pipeline, mobile app"
              maxLength={200}
              autoFocus
            />
          </label>
          <label className={styles.formLabel}>
            Scope
            <select className={styles.formSelect} value={scope} onChange={(e) => setScope(e.target.value as 'read' | 'admin')}>
              <option value="read">read — Chat, tasks, files, skills</option>
              <option value="admin">admin — Full access including key management</option>
            </select>
          </label>
          <label className={`${styles.formLabel} ${styles.checkRow}`}>
            <input
              type="checkbox"
              checked={expiryEnabled}
              onChange={(e) => setExpiryEnabled(e.target.checked)}
            />
            Set expiry date
          </label>
          {expiryEnabled && (
            <label className={styles.formLabel}>
              Expires at
              <input
                type="datetime-local"
                className={styles.formInput}
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                min={new Date().toISOString().slice(0, 16)}
              />
            </label>
          )}
          <div className={styles.modalActions}>
            <button type="button" className={styles.cancelBtn} onClick={onClose} disabled={creating}>
              Cancel
            </button>
            <button type="submit" className={styles.createBtn} disabled={creating}>
              {creating ? 'Creating…' : 'Create key'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---- Raw Key Display (shown once) -------------------------------------------

interface RawKeyDisplayProps {
  rawKey: string
  onDone: () => void
}

function RawKeyDisplay({ rawKey, onDone }: RawKeyDisplayProps) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(rawKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modal}>
        <div className={styles.rawKeyWarning}>
          <AlertTriangle size={16} />
          Copy this key now — it will never be shown again.
        </div>
        <div className={styles.rawKeyBox}>
          <code className={styles.rawKeyCode}>{rawKey}</code>
          <button className={styles.copyBtn} onClick={copy} title="Copy to clipboard">
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
        <div className={styles.modalActions}>
          <button className={styles.createBtn} onClick={onDone}>
            I've copied the key
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Revoke Confirm ---------------------------------------------------------

interface RevokeConfirmProps {
  keyRecord: ApiKeyRecord
  onConfirm: () => void
  onCancel: () => void
  revoking: boolean
}

function RevokeConfirm({ keyRecord, onConfirm, onCancel, revoking }: RevokeConfirmProps) {
  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h3 className={styles.modalTitle}>Revoke API Key</h3>
        <p className={styles.modalBody}>
          Revoke <strong>{keyRecord.description || keyRecord.key_prefix + '…'}</strong>?
          Any services using this key will immediately lose access.
        </p>
        <div className={styles.modalActions}>
          <button className={styles.cancelBtn} onClick={onCancel} disabled={revoking}>Cancel</button>
          <button className={styles.dangerBtn} onClick={onConfirm} disabled={revoking}>
            {revoking ? 'Revoking…' : 'Revoke key'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Audit Panel ------------------------------------------------------------

interface AuditPanelProps {
  keyId: string
}

function AuditPanel({ keyId }: AuditPanelProps) {
  const [events, setEvents] = useState<ApiKeyEventRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetchApiKeyEvents(keyId)
      .then((r) => { setEvents(r.events); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [keyId])

  if (loading) return <p className={styles.hint}>Loading events…</p>
  if (error) return <p className={`${styles.hint} ${styles.errorText}`}>{error}</p>
  if (events.length === 0) return <p className={styles.hint}>No events yet.</p>

  return (
    <table className={styles.auditTable}>
      <thead>
        <tr>
          <th>Event</th>
          <th>When</th>
        </tr>
      </thead>
      <tbody>
        {events.map((ev) => (
          <tr key={ev.id}>
            <td>
              <span className={`${styles.eventBadge} ${styles[`event_${ev.event_type}`] ?? ''}`}>
                {ev.event_type}
              </span>
            </td>
            <td className={styles.auditDate}>{formatDate(ev.occurred_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---- Key Row ----------------------------------------------------------------

interface KeyRowProps {
  keyRecord: ApiKeyRecord
  onRevoke: (key: ApiKeyRecord) => void
}

function KeyRow({ keyRecord, onRevoke }: KeyRowProps) {
  const [expanded, setExpanded] = useState(false)
  const { label, variant } = statusLabel(keyRecord)

  return (
    <>
      <tr className={`${styles.keyRow} ${!keyRecord.is_active ? styles.keyRowInactive : ''}`}>
        <td className={styles.keyDescription}>
          <button className={styles.expandBtn} onClick={() => setExpanded((v) => !v)} title="Toggle audit log">
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
          <span className={styles.keyDesc}>{keyRecord.description || <em className={styles.noDesc}>No description</em>}</span>
        </td>
        <td>
          <code className={styles.keyPrefix}>{keyRecord.key_prefix}…</code>
        </td>
        <td>
          <span className={`${styles.scopeBadge} ${styles[`scope_${keyRecord.scope}`]}`}>
            {keyRecord.scope}
          </span>
        </td>
        <td>
          <span className={`${styles.statusBadge} ${styles[`status_${variant}`]}`}>
            {label}
          </span>
        </td>
        <td className={styles.dateCell}>{formatDate(keyRecord.created_at)}</td>
        <td className={styles.dateCell}>{formatDate(keyRecord.last_used_at)}</td>
        <td className={styles.dateCell}>{formatDate(keyRecord.expires_at)}</td>
        <td>
          {keyRecord.is_active && (
            <button
              className={styles.revokeBtn}
              onClick={() => onRevoke(keyRecord)}
              title="Revoke key"
            >
              <Trash2 size={13} />
            </button>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className={styles.auditRow}>
          <td colSpan={8}>
            <div className={styles.auditWrapper}>
              <AuditPanel keyId={keyRecord.id} />
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ---- Main View --------------------------------------------------------------

export function KeyManagementView() {
  const [keys, setKeys] = useState<ApiKeyRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [pendingRawKey, setPendingRawKey] = useState<string | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyRecord | null>(null)
  const [revoking, setRevoking] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listApiKeys()
      setKeys(res.keys)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handleCreate(description: string, scope: 'read' | 'admin', expiresAt: string | null) {
    setCreating(true)
    try {
      const res = await createApiKey({ description, scope, expires_at: expiresAt })
      setShowCreate(false)
      setPendingRawKey(res.raw_key)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke() {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await revokeApiKey(revokeTarget.id)
      setRevokeTarget(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRevoking(false)
    }
  }

  const activeCount = keys.filter((k) => k.is_active).length

  return (
    <div className={styles.root}>
      <div className={styles.topBar}>
        <div className={styles.titleBlock}>
          <h2 className={styles.pageTitle}>API Keys</h2>
          <span className={styles.countPill}>{activeCount} active</span>
        </div>
        <div className={styles.topActions}>
          <button className={styles.refreshBtn} onClick={load} title="Refresh">
            <RefreshCw size={14} />
          </button>
          <button className={styles.createKeyBtn} onClick={() => setShowCreate(true)}>
            <Plus size={14} />
            New key
          </button>
        </div>
      </div>

      {error && <p className={`${styles.hint} ${styles.errorText}`}>{error}</p>}
      {loading && <p className={styles.hint}>Loading…</p>}

      {!loading && keys.length === 0 && (
        <div className={styles.empty}>
          <Key size={28} className={styles.emptyIcon} />
          <p>No API keys yet.</p>
          <button className={styles.createKeyBtn} onClick={() => setShowCreate(true)}>
            <Plus size={14} />
            Create first key
          </button>
        </div>
      )}

      {keys.length > 0 && (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Description</th>
                <th>Prefix</th>
                <th>Scope</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last used</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <KeyRow key={k.id} keyRecord={k} onRevoke={setRevokeTarget} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateKeyModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
          creating={creating}
        />
      )}

      {pendingRawKey && (
        <RawKeyDisplay rawKey={pendingRawKey} onDone={() => setPendingRawKey(null)} />
      )}

      {revokeTarget && (
        <RevokeConfirm
          keyRecord={revokeTarget}
          onConfirm={handleRevoke}
          onCancel={() => setRevokeTarget(null)}
          revoking={revoking}
        />
      )}
    </div>
  )
}
