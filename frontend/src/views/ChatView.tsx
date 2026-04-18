import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Copy, RotateCcw } from 'lucide-react'
import { approveArtifact, cancelTask, fetchArtifacts, fetchConfig, revokeArtifactApproval, sendChat } from '../api/client'
import { useChatSessions } from '../contexts/ChatSessionsContext'
import { useTaskDrafts } from '../contexts/TaskDraftsContext'
import { useSchedulerTask } from '../contexts/SchedulerTaskContext'
import { StatusIndicator } from '../components/StatusIndicator'
import { TaskRunningBanner } from '../components/layout/TaskRunningBanner'
import { RunTimeline } from '../components/RunTimeline'
import { PreviewPanel } from '../components/PreviewPanel'
import { usePolling } from '../hooks/usePolling'
import { useTaskStream } from '../hooks/useTaskStream'
import styles from './ChatView.module.css'

const VISUAL_STATE_KEY = 'titanshift-workflow-visual-state'
const VISUAL_EVENT_NAME = 'titanshift:workflow-visual'

export function ChatView() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [promoteMsg, setPromoteMsg] = useState<string | null>(null)
  const [preferredBackend, setPreferredBackend] = useState<string | null>(null)
  const [workflowMode, setWorkflowMode] = useState<'lightning' | 'superpowered'>('lightning')
  const [specApproved, setSpecApproved] = useState(false)
  const [planApproved, setPlanApproved] = useState(false)
  const [planTasksText, setPlanTasksText] = useState('')
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedMessageIndexes, setSelectedMessageIndexes] = useState<number[]>([])
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [pendingApprovals, setPendingApprovals] = useState<string[]>([])
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [blockedPrompt, setBlockedPrompt] = useState<string | null>(null)
  const [workflowPhase, setWorkflowPhase] = useState<'idle' | 'routing' | 'approval' | 'implement' | 'review' | 'deliver' | 'error'>('idle')
  const [workflowPanelOpen, setWorkflowPanelOpen] = useState(true)
  const [artifactDockOpen, setArtifactDockOpen] = useState(false)
  const [artifactBusy, setArtifactBusy] = useState(false)
  const [liveRun, setLiveRun] = useState(false)
  const [timelineOpen, setTimelineOpen] = useState(true)
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const { state: streamState, startStream } = useTaskStream()
  const { currentSession, appendMessage } = useChatSessions()
  const { promoteSessionToDraft, promoteSelectionToDraft } = useTaskDrafts()
  const { concurrencyMode, isTaskRunning } = useSchedulerTask()
  const { data: artifactsData, refresh: refreshArtifacts } = usePolling(fetchArtifacts, { interval: 15000 })
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const messages = currentSession.messages

  const taskCandidate = useMemo(() => {
    const userMessages = messages.filter((m) => m.role === 'user')
    const totalChars = userMessages.reduce((sum, m) => sum + m.text.length, 0)
    return userMessages.length >= 4 || totalChars >= 500
  }, [messages])

  const canSend = useMemo(() => input.trim().length > 0 && !sending, [input, sending])
  const planTaskCount = useMemo(
    () => planTasksText.split('\n').map((line) => line.trim()).filter(Boolean).length,
    [planTasksText],
  )
  const isTaskQueueMode = concurrencyMode === 'single-run' && isTaskRunning

  useEffect(() => {
    let mounted = true
    void fetchConfig()
      .then((cfg) => {
        if (!mounted) return
        const backend = cfg['model.default_backend']
        if (typeof backend === 'string' && backend.trim().length > 0) {
          setPreferredBackend(backend)
        }
        const configuredMode = cfg['orchestrator.workflow_mode']
        if (configuredMode === 'lightning' || configuredMode === 'superpowered') {
          setWorkflowMode(configuredMode)
        }
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    setError(null)
    setInput('')
    setSelectionMode(false)
    setSelectedMessageIndexes([])
    setPendingApprovals([])
    setBlockedPrompt(null)
  }, [currentSession.id])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  useEffect(() => {
    const nextState = {
      mode: workflowMode,
      active: sending,
      specApproved,
      planApproved,
      planTaskCount,
      phase: workflowPhase,
    }

    try {
      window.localStorage.setItem(VISUAL_STATE_KEY, JSON.stringify(nextState))
      window.dispatchEvent(new CustomEvent(VISUAL_EVENT_NAME, { detail: nextState }))
    } catch {
      // Ignore storage/event failures; chat should still function normally.
    }
  }, [workflowMode, sending, specApproved, planApproved, planTaskCount, workflowPhase])

  async function sendPrompt(rawText: string, options?: { replay?: boolean }) {
    const text = rawText.trim()
    if (!text || sending) return

    // Capture history BEFORE appending the new user message — appendMessage
    // queues a React state update that hasn't re-rendered yet at this point,
    // so `messages` still reflects the prior conversation (all prior turns).
    const priorMessages = messages.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.text,
    }))

    if (!options?.replay) {
      appendMessage({ role: 'user', text })
    }
    setInput('')
    setSending(true)
    setError(null)
    setWorkflowPhase('routing')

    // ── Live Run (streaming) path ────────────────────────────────────────────
    if (liveRun) {
      const requestBody: Record<string, unknown> = {
        prompt: text,
        ...(priorMessages.length > 0 ? { history: priorMessages } : {}),
        ...(preferredBackend ? { model_backend: preferredBackend } : {}),
        workflow_mode: workflowMode,
      }
      try {
        await startStream(requestBody)
        // Response will come via streamState; append a placeholder then update
        // once done event arrives. We watch streamState in the effect below.
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setWorkflowPhase('error')
      } finally {
        setSending(false)
      }
      return
    }

    try {
      const parsedPlanTasks = workflowMode === 'superpowered'
        ? planTasksText
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)
          .map((title) => ({ title }))
        : []
      const result = await sendChat({
        prompt: text,
        ...(priorMessages.length > 0 ? { history: priorMessages } : {}),
        ...(preferredBackend ? { model_backend: preferredBackend } : {}),
        workflow_mode: workflowMode,
        ...(workflowMode === 'superpowered'
          ? {
              spec_approved: specApproved,
              plan_approved: planApproved,
              ...(parsedPlanTasks.length > 0 ? { plan_tasks: parsedPlanTasks } : {}),
            }
          : {}),
      })
      if (result.task_id) setCurrentTaskId(result.task_id)
      const reply = (
        (result.response ?? '').trim()
        || (result.error ?? '').trim()
        || (result.success ? '' : 'Request completed without an assistant response.')
        || 'No response returned.'
      )
      appendMessage({ role: 'assistant', text: reply })
      if (result.mode === 'approval-gate') {
        setPendingApprovals(Array.isArray(result.missing_approvals) ? result.missing_approvals : [])
        setBlockedPrompt(text)
        setWorkflowPhase('approval')
      } else {
        setPendingApprovals([])
        setBlockedPrompt(null)
        if (!result.success) {
          setWorkflowPhase('error')
        } else if (workflowMode === 'superpowered') {
          setWorkflowPhase(parsedPlanTasks.length > 0 ? 'review' : 'implement')
        } else {
          setWorkflowPhase('deliver')
        }
      }
      if (!result.success && result.error) {
        setError(result.error)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      appendMessage({ role: 'assistant', text: 'Request failed. Check Health and provider settings, then try again.' })
      setWorkflowPhase('error')
    } finally {
      setSending(false)
      setCurrentTaskId(null)
      setCancelling(false)
    }
  }

  // When a streaming run finishes, append the final response as an assistant message
  useEffect(() => {
    if (streamState.status === 'done' && streamState.finalResponse) {
      appendMessage({ role: 'assistant', text: streamState.finalResponse })
      setWorkflowPhase('deliver')
      setSending(false)
    } else if (streamState.status === 'error' && streamState.error) {
      setError(streamState.error)
      setWorkflowPhase('error')
      setSending(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamState.status])

  async function copyMessage(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1200)
    } catch {
      setError('Copy failed. Clipboard permission may be blocked.')
    }
  }

  async function send() {
    await sendPrompt(input)
  }

  async function approveRequestedApprovals() {
    const approvals = pendingApprovals.filter((value): value is 'spec' | 'plan' => value === 'spec' || value === 'plan')
    if (approvals.length === 0 || approvalBusy) return
    setApprovalBusy(true)
    try {
      for (const approval of approvals) {
        await approveArtifact(approval)
      }
      if (approvals.includes('spec')) setSpecApproved(true)
      if (approvals.includes('plan')) setPlanApproved(true)
      appendMessage({
        role: 'assistant',
        text: `Approval recorded for: ${approvals.join(', ')}. Resuming request automatically...`,
      })
      setPendingApprovals([])
      setWorkflowPhase('implement')
      setError(null)
      await refreshArtifacts()
      if (blockedPrompt && blockedPrompt.trim().length > 0) {
        await sendPrompt(blockedPrompt, { replay: true })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setApprovalBusy(false)
    }
  }

  function denyRequestedApprovals() {
    setPendingApprovals([])
    setBlockedPrompt(null)
    setWorkflowPhase('idle')
    appendMessage({ role: 'assistant', text: 'Approval request dismissed.' })
  }

  async function toggleArtifactApproval(artifactType: 'spec' | 'plan', approve: boolean) {
    if (artifactBusy) return
    setArtifactBusy(true)
    try {
      if (approve) {
        await approveArtifact(artifactType)
      } else {
        await revokeArtifactApproval(artifactType)
      }
      if (artifactType === 'spec') setSpecApproved(approve)
      if (artifactType === 'plan') setPlanApproved(approve)
      await refreshArtifacts()
    } finally {
      setArtifactBusy(false)
    }
  }

  function promoteCurrentSession() {
    const draft = promoteSessionToDraft(currentSession)
    if (draft) {
      setPromoteMsg(`Draft created: ${draft.title}`)
    } else {
      setPromoteMsg('Not enough user instructions to generate a task draft yet.')
    }
  }

  function toggleSelectedMessage(index: number) {
    setSelectedMessageIndexes((prev) => (
      prev.includes(index) ? prev.filter((value) => value !== index) : [...prev, index]
    ))
  }

  function promoteSelectedMessages() {
    const draft = promoteSelectionToDraft(currentSession, selectedMessageIndexes)
    if (draft) {
      setPromoteMsg(`Draft created from selection: ${draft.title}`)
      setSelectionMode(false)
      setSelectedMessageIndexes([])
    } else {
      setPromoteMsg('Select one or more user messages with instruction-like content first.')
    }
  }

  return (
    <div className={styles.root}>
      <TaskRunningBanner />
      <div className={styles.topBar}>
        <div className={styles.topActions}>
          <button className={styles.promoteBtn} onClick={promoteCurrentSession}>Promote To Task</button>
          <button
            className={`${styles.promoteBtn} ${selectionMode ? styles.promoteBtnActive : ''}`}
            onClick={() => {
              setSelectionMode((prev) => !prev)
              setSelectedMessageIndexes([])
            }}
          >
            {selectionMode ? 'Cancel Selection' : 'Select Messages'}
          </button>
          {selectionMode && (
            <button
              className={styles.promoteBtn}
              onClick={promoteSelectedMessages}
              disabled={selectedMessageIndexes.length === 0}
            >
              Promote Selected ({selectedMessageIndexes.length})
            </button>
          )}
        </div>
        {taskCandidate && <span className={styles.candidateHint}>Complex thread detected: good task candidate</span>}
      </div>

      <div className={styles.workflowBar}>
        <div className={styles.workflowGroup}>
          <span className={styles.workflowLabel}>Workflow</span>
          <button
            className={`${styles.modeChip} ${workflowMode === 'lightning' ? styles.modeChipActive : ''}`}
            onClick={() => setWorkflowMode('lightning')}
            disabled={sending}
          >
            Lightning
          </button>
          <button
            className={`${styles.modeChip} ${workflowMode === 'superpowered' ? styles.modeChipActive : ''}`}
            onClick={() => setWorkflowMode('superpowered')}
            disabled={sending}
          >
            Superpowered
          </button>
        </div>
        <div className={styles.workflowBarActions}>
          <label className={styles.toggleLabel} title="Use streaming /chat/stream endpoint and show live timeline">
            <input
              type="checkbox"
              checked={liveRun}
              onChange={(e) => setLiveRun(e.target.checked)}
              disabled={sending}
            />
            Live Run
          </label>
          <span className={`badge ${workflowPhase === 'error' ? 'badge-error' : workflowPhase === 'approval' ? 'badge-warn' : 'badge-ok'}`}>
            {workflowPhase}
          </span>
          {workflowMode === 'superpowered' && (
            <button className={styles.collapseBtn} onClick={() => setWorkflowPanelOpen((value) => !value)}>
              {workflowPanelOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              Workflow Details
            </button>
          )}
        </div>
      </div>

      {workflowMode === 'superpowered' && workflowPanelOpen && (
        <div className={styles.planComposer}>
          <div className={styles.workflowMeta}>
            <label className={styles.toggleLabel}>
              <input type="checkbox" checked={specApproved} onChange={(e) => setSpecApproved(e.target.checked)} disabled={sending} />
              Spec approved
            </label>
            <label className={styles.toggleLabel}>
              <input type="checkbox" checked={planApproved} onChange={(e) => setPlanApproved(e.target.checked)} disabled={sending} />
              Plan approved
            </label>
          </div>
          <p className={styles.planHint}>Optional review-loop tasks, one per line</p>
          <textarea
            className={styles.planInput}
            placeholder={"Create spec artifact\nWrite plan artifact\nImplement endpoint"}
            rows={3}
            value={planTasksText}
            onChange={(e) => setPlanTasksText(e.target.value)}
            disabled={sending}
          />
        </div>
      )}

      <div className={styles.messages}>
        {messages.length === 0 ? (
          <div className={styles.empty}>
            <p className={styles.emptyHint}>Pick a workflow, then start a request.</p>
          </div>
        ) : (
          <div className={styles.thread}>
            {messages.map((m, i) => (
              <div key={`${m.role}-${i}`} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.assistant}`}>
                <div className={styles.msgHead}>
                  <p className={styles.msgRole}>{m.role === 'user' ? 'You' : 'TitanShift'}</p>
                  <div className={styles.msgTools}>
                    {selectionMode && m.role === 'user' && (
                      <label className={styles.selectLabel}>
                        <input
                          type="checkbox"
                          checked={selectedMessageIndexes.includes(i)}
                          onChange={() => toggleSelectedMessage(i)}
                        />
                        Select
                      </label>
                    )}
                    <button
                      className={styles.msgToolBtn}
                      title={copiedKey === `${m.role}-${i}` ? 'Copied' : 'Copy'}
                      onClick={() => void copyMessage(m.text, `${m.role}-${i}`)}
                    >
                      <Copy size={13} />
                    </button>
                    {m.role === 'user' && (
                      <button
                        className={styles.msgToolBtn}
                        title="Resend"
                        disabled={sending}
                        onClick={() => void sendPrompt(m.text)}
                      >
                        <RotateCcw size={13} />
                      </button>
                    )}
                  </div>
                </div>
                <p className={styles.msgText}>{m.text}</p>
                {m.timestamp && (
                  <p className={styles.msgTime}>
                    {new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        {pendingApprovals.length > 0 && (
          <div className={styles.approvalCard}>
            <p className={styles.approvalTitle}>Approval Required</p>
            <p className={styles.approvalText}>
              Superpowered mode is waiting on: {pendingApprovals.join(', ')}.
            </p>
            <div className={styles.approvalActions}>
              <button className={styles.approvalApproveBtn} onClick={() => void approveRequestedApprovals()} disabled={approvalBusy}>
                {approvalBusy ? 'Approving…' : 'Approve'}
              </button>
              <button className={styles.approvalDenyBtn} onClick={denyRequestedApprovals} disabled={approvalBusy}>
                Deny
              </button>
            </div>
          </div>
        )}
        {sending && !liveRun && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <StatusIndicator isActive />
            {currentTaskId && (
              <button
                className={styles.cancelBtn}
                disabled={cancelling}
                onClick={() => {
                  if (!currentTaskId || cancelling) return
                  setCancelling(true)
                  void cancelTask(currentTaskId).catch(() => {}).finally(() => setCancelling(false))
                }}
              >
                {cancelling ? 'Cancelling…' : 'Cancel'}
              </button>
            )}
          </div>
        )}
        {liveRun && streamState.status !== 'idle' && (
          <div>
            <button
              className={styles.collapseBtn}
              onClick={() => setTimelineOpen((v) => !v)}
              style={{ margin: '4px 0' }}
            >
              {timelineOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              Run Timeline
            </button>
            {timelineOpen && (
              <RunTimeline events={streamState.events} status={streamState.status} />
            )}
            {streamState.status === 'done' && (
              <PreviewPanel
                patchSummaries={streamState.patchSummaries}
                updatedPaths={streamState.updatedPaths}
                onFeedback={(feedback) => void sendPrompt(feedback)}
                feedbackLoading={sending}
              />
            )}
          </div>
        )}
        {promoteMsg && <p className={`${styles.error} text-info`}>{promoteMsg}</p>}
        {error && <p className={`${styles.error} text-error`}>{error}</p>}
        <div ref={messagesEndRef} />
      </div>

      <div className={styles.inputRow}>
        <textarea
          className={styles.input}
          placeholder="Message..."
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
        />
        <div className={styles.sendActions}>
          {isTaskQueueMode && input.trim().length > 0 ? (
            <>
              <button
                className={`${styles.sendBtn} ${styles.sendBtnQueue}`}
                title="Queue message while task is running"
                onClick={() => void send()}
              >
                Queue
              </button>
              <button
                className={`${styles.sendBtn} ${styles.sendBtnSecondary}`}
                title="Run in parallel (concurrency mode off)"
                disabled
              >
                Parallel Off
              </button>
            </>
          ) : (
            <button className={styles.sendBtn} title="Send" onClick={() => void send()} disabled={!canSend}>
              {sending ? '...' : '▶'}
            </button>
          )}
        </div>
      </div>

      <div className={styles.dockBar}>
        <button className={styles.collapseBtn} onClick={() => setArtifactDockOpen((value) => !value)}>
          {artifactDockOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Artifact Dock
        </button>
      </div>
      {artifactDockOpen && (
        <div className={styles.artifactDock}>
          {(artifactsData ?? []).slice(0, 6).map((artifact) => (
            <div key={artifact.path} className={styles.artifactRow}>
              <div>
                <p className={styles.artifactName}>{artifact.filename}</p>
                <p className={styles.artifactMeta}>{artifact.artifact_type} • {Math.max(1, Math.round(artifact.size / 1024))} KB</p>
              </div>
              <div className={styles.artifactActions}>
                <span className={`badge ${artifact.approved ? 'badge-ok' : 'badge-warn'}`}>{artifact.approved ? 'approved' : 'pending'}</span>
                <button
                  className={styles.artifactBtn}
                  onClick={() => void toggleArtifactApproval(artifact.artifact_type, !artifact.approved)}
                  disabled={artifactBusy}
                >
                  {artifact.approved ? 'Revoke' : 'Approve'}
                </button>
              </div>
            </div>
          ))}
          {(artifactsData ?? []).length === 0 && <p className={styles.emptyHint}>No spec or plan artifacts found yet.</p>}
        </div>
      )}
    </div>
  )
}
