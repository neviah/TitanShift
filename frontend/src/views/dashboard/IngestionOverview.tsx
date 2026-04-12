import { usePolling } from '../../hooks/usePolling'
import { fetchIngestionOverview, graphifyIngest } from '../../api/client'
import styles from './IngestionOverview.module.css'
import { RefreshCw, Zap, AlertCircle, CheckCircle } from 'lucide-react'
import { useState } from 'react'

type IngestState = 'idle' | 'ingesting' | 'success' | 'error'

export function IngestionOverview() {
  const { data, error, loading, refresh } = usePolling(fetchIngestionOverview, { interval: 10000 })
  const [inputText, setInputText] = useState('')
  const [ingestState, setIngestState] = useState<IngestState>('idle')
  const [ingestError, setIngestError] = useState<string | null>(null)
  const [ingestResult, setIngestResult] = useState<{ nodes: number; edges: number } | null>(null)

  async function handleIngest() {
    if (!inputText.trim()) return
    
    setIngestState('ingesting')
    setIngestError(null)
    setIngestResult(null)
    
    try {
      const result = await graphifyIngest({
        text: inputText,
        metadata: { source: 'ui_manual_ingestion' },
      })
      
      if (result.ok) {
        setIngestState('success')
        setIngestResult({
          nodes: result.nodes_added,
          edges: result.edges_added,
        })
        setInputText('')
        setTimeout(() => {
          setIngestState('idle')
          void refresh()
        }, 2000)
      } else {
        setIngestState('error')
        setIngestError('Ingestion failed')
      }
    } catch (e) {
      setIngestState('error')
      setIngestError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.title}>Ingestion</span>
        <button className={styles.refreshBtn} onClick={refresh} title="Refresh">
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <p className={styles.hint}>Loading…</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}

      {data && (
        <>
          <div className={styles.grid}>
            <Stat label="Total Ingested"  value={data.stats.total_ingested} />
            <Stat label="Deduplicated"    value={data.stats.total_deduplicated} />
            <Stat label="Embeddings"      value={data.stats.total_embeddings} accent />
          </div>

          {/* Graphify Ingestion Section */}
          <section className={styles.ingestSection}>
            <h4 className={styles.sectionTitle}>Graphify Text Ingestion</h4>
            <textarea
              className={styles.textarea}
              placeholder="Paste text or logs here to extract entities and relationships…"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={ingestState === 'ingesting'}
              rows={4}
            />
            <div className={styles.ingestActions}>
              <button
                className={styles.ingestBtn}
                onClick={handleIngest}
                disabled={ingestState === 'ingesting' || !inputText.trim()}
              >
                <Zap size={14} />
                {ingestState === 'ingesting' ? 'Ingesting…' : 'Ingest'}
              </button>
              {ingestState === 'success' && ingestResult && (
                <span className={`${styles.ingestResult} text-ok`}>
                  <CheckCircle size={13} /> {ingestResult.nodes} nodes, {ingestResult.edges} edges
                </span>
              )}
              {ingestState === 'error' && (
                <span className={`${styles.ingestResult} text-error`}>
                  <AlertCircle size={13} /> {ingestError || 'Error'}
                </span>
              )}
            </div>
          </section>

          {data.recent_ingestions.length > 0 && (
            <section>
              <h4 className={styles.sectionTitle}>Recent</h4>
              <ul className={styles.list}>
                {data.recent_ingestions.slice(0, 5).map((ev) => (
                  <li key={ev.id} className={styles.item}>
                    <span className={styles.source}>{ev.source}</span>
                    <span className={`badge ${ev.status === 'ok' ? 'badge-ok' : 'badge-warn'}`}>
                      {ev.status}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  const cls = accent ? 'text-accent' : 'text-primary'
  return (
    <div className={styles.stat}>
      <span className={`${styles.statValue} ${cls}`}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}
