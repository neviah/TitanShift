import { useEffect, useMemo, useState } from 'react'
import {
  Bot,
  CheckCheck,
  FileCheck,
  FileText,
  Gauge,
  Layers,
  Rocket,
  SearchCheck,
  Sparkles,
  Wand2,
  Wrench,
} from 'lucide-react'
import { usePolling } from '../../hooks/usePolling'
import { fetchLogs, fetchStatus } from '../../api/client'
import styles from './ModuleBackdrop.module.css'

const VISUAL_STATE_KEY = 'titanshift-workflow-visual-state'
const VISUAL_EVENT_NAME = 'titanshift:workflow-visual'

type WorkflowMode = 'lightning' | 'superpowered'

interface WorkflowVisualState {
  mode: WorkflowMode
  active: boolean
  specApproved: boolean
  planApproved: boolean
  planTaskCount: number
}

interface OrbitNodeSpec {
  key: string
  label: string
  Icon: React.ComponentType<{ size?: number; strokeWidth?: number }>
  emphasis?: 'neutral' | 'approved' | 'alert'
}

interface OrbitRingSpec {
  key: string
  radiusX: number
  radiusY: number
  tilt: number
  speed: number
  direction: 1 | -1
  nodes: OrbitNodeSpec[]
}

const DEFAULT_VISUAL_STATE: WorkflowVisualState = {
  mode: 'lightning',
  active: false,
  specApproved: false,
  planApproved: false,
  planTaskCount: 0,
}

function loadVisualState(): WorkflowVisualState {
  try {
    const raw = window.localStorage.getItem(VISUAL_STATE_KEY)
    if (!raw) return DEFAULT_VISUAL_STATE
    const parsed = JSON.parse(raw) as Partial<WorkflowVisualState>
    return {
      mode: parsed.mode === 'superpowered' ? 'superpowered' : 'lightning',
      active: Boolean(parsed.active),
      specApproved: Boolean(parsed.specApproved),
      planApproved: Boolean(parsed.planApproved),
      planTaskCount: Number.isFinite(parsed.planTaskCount) ? Number(parsed.planTaskCount) : 0,
    }
  } catch {
    return DEFAULT_VISUAL_STATE
  }
}

function buildLightningRings(): OrbitRingSpec[] {
  return [
    {
      key: 'lightning-primary',
      radiusX: 240,
      radiusY: 96,
      tilt: -12,
      speed: 24,
      direction: 1,
      nodes: [
        { key: 'prompt', label: 'Prompt', Icon: Sparkles },
        { key: 'agent', label: 'Agent', Icon: Bot },
        { key: 'tools', label: 'Tools', Icon: Wrench },
        { key: 'ship', label: 'Response', Icon: Rocket },
      ],
    },
  ]
}

function buildSuperpoweredRings(state: WorkflowVisualState): OrbitRingSpec[] {
  return [
    {
      key: 'superpowered-inner',
      radiusX: 172,
      radiusY: 72,
      tilt: -16,
      speed: 30,
      direction: 1,
      nodes: [
        {
          key: 'spec',
          label: state.specApproved ? 'Spec Locked' : 'Spec',
          Icon: FileCheck,
          emphasis: state.specApproved ? 'approved' : 'neutral',
        },
        {
          key: 'plan',
          label: state.planApproved ? 'Plan Locked' : 'Plan',
          Icon: FileText,
          emphasis: state.planApproved ? 'approved' : 'neutral',
        },
        { key: 'build', label: 'Implement', Icon: Wand2 },
        { key: 'review', label: 'Review', Icon: SearchCheck },
      ],
    },
    {
      key: 'superpowered-outer',
      radiusX: 286,
      radiusY: 126,
      tilt: 18,
      speed: 42,
      direction: -1,
      nodes: [
        { key: 'verify', label: 'Verify', Icon: CheckCheck },
        { key: 'artifacts', label: 'Artifacts', Icon: Layers },
        {
          key: 'tasks',
          label: state.planTaskCount > 0 ? `${state.planTaskCount} Tasks` : 'Tasks',
          Icon: Gauge,
          emphasis: state.planTaskCount > 0 ? 'approved' : 'neutral',
        },
        { key: 'ship', label: 'Release', Icon: Rocket },
      ],
    },
  ]
}

function polarToTiltedCartesian(angleDeg: number, radiusX: number, radiusY: number, tiltDeg: number) {
  const radians = (angleDeg * Math.PI) / 180
  const tilt = (tiltDeg * Math.PI) / 180
  const x = radiusX * Math.cos(radians)
  const y = radiusY * Math.sin(radians)
  return {
    x: x * Math.cos(tilt) - y * Math.sin(tilt),
    y: x * Math.sin(tilt) + y * Math.cos(tilt),
    scale: Math.cos(radians) > 0 ? 1.06 : 0.9,
    depth: Math.cos(radians),
  }
}

export function ModuleBackdrop() {
  const { data } = usePolling(fetchStatus, { interval: 12000 })
  const { data: logs } = usePolling(() => fetchLogs(40), { interval: 4000 })
  const [visualState, setVisualState] = useState<WorkflowVisualState>(() => loadVisualState())
  const [frameMs, setFrameMs] = useState(0)

  useEffect(() => {
    const handleVisualEvent = (event: Event) => {
      const detail = (event as CustomEvent<WorkflowVisualState>).detail
      if (detail) setVisualState(detail)
    }

    setVisualState(loadVisualState())
    window.addEventListener(VISUAL_EVENT_NAME, handleVisualEvent as EventListener)
    return () => window.removeEventListener(VISUAL_EVENT_NAME, handleVisualEvent as EventListener)
  }, [])

  useEffect(() => {
    let frame = 0
    const tick = () => {
      setFrameMs(performance.now())
      frame = window.setTimeout(tick, 42)
    }
    tick()
    return () => window.clearTimeout(frame)
  }, [])

  const recentRuntimeActivity = useMemo(() => {
    return (logs?.items ?? []).some((item) => {
      const eventType = String(item.event_type ?? '').toLowerCase()
      return eventType.includes('task_') || eventType.includes('module_error') || eventType.includes('workflow_')
    })
  }, [logs])

  const mode = visualState.mode
  const isActive = visualState.active || recentRuntimeActivity
  const rings = mode === 'superpowered' ? buildSuperpoweredRings(visualState) : buildLightningRings()
  const centerStatus = mode === 'superpowered'
    ? (data?.subagents_enabled ? 'review loop armed' : 'subagents offline')
    : 'rapid path'
  const centerMeta = mode === 'superpowered'
    ? `${visualState.specApproved ? 'spec' : 'draft'} / ${visualState.planApproved ? 'plan' : 'awaiting plan'}`
    : (data?.model_connected === false ? 'model offline' : 'model linked')

  return (
    <div className={`${styles.root} ${isActive ? styles.rootActive : ''}`} aria-hidden>
      <div className={styles.fieldGlow} />

      {rings.map((ring) => (
        <div key={ring.key} className={styles.ringShell}>
          <div
            className={`${styles.ringTrace} ${isActive ? styles.ringTraceActive : ''}`}
            style={{
              width: `${ring.radiusX * 2}px`,
              height: `${ring.radiusY * 2}px`,
              transform: `translate(-50%, -50%) rotate(${ring.tilt}deg)`,
            }}
          />

          {ring.nodes.map((node, index) => {
            const baseAngle = (360 / ring.nodes.length) * index
            const progress = ((frameMs / 1000) * (360 / ring.speed) * ring.direction) % 360
            const point = polarToTiltedCartesian(baseAngle + progress, ring.radiusX, ring.radiusY, ring.tilt)
            const emphasisClass = node.emphasis === 'approved'
              ? styles.nodeApproved
              : node.emphasis === 'alert'
                ? styles.nodeAlert
                : ''
            return (
              <div
                key={node.key}
                className={`${styles.node} ${isActive ? styles.nodeActive : ''} ${emphasisClass}`}
                style={{
                  left: `calc(50% + ${point.x}px)`,
                  top: `calc(50% + ${point.y}px)`,
                  transform: `translate(-50%, -50%) scale(${point.scale})`,
                  zIndex: point.depth > 0 ? 3 : 1,
                }}
                title={node.label}
              >
                <node.Icon size={20} strokeWidth={1.8} />
                <span className={styles.label}>{node.label}</span>
              </div>
            )
          })}
        </div>
      ))}

      <div className={`${styles.core} ${isActive ? styles.coreActive : ''}`}>
        <div className={styles.coreHalo} />
        <div className={styles.coreInner}>
          <span className={styles.coreEyebrow}>{mode}</span>
          <p className={styles.coreTitle}>TitanShift</p>
          <p className={styles.coreStatus}>{centerStatus}</p>
          <p className={styles.coreMeta}>{centerMeta}</p>
        </div>
      </div>
    </div>
  )
}
