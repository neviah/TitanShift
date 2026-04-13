import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  Binary,
  Bot,
  Compass,
  FileCheck,
  FileText,
  Gauge,
  Layers,
  Network,
  Rocket,
  SearchCheck,
  ShieldCheck,
  Spline,
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
  family: WorkflowMode | 'shared'
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
      family: 'lightning',
      nodes: [
        { key: 'request', label: 'Request', Icon: Compass },
        { key: 'orchestrator', label: 'Orchestrator', Icon: Bot },
        { key: 'tools', label: 'Tooling', Icon: Wrench },
        { key: 'response', label: 'Delivery', Icon: Rocket },
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
      family: 'superpowered',
      nodes: [
        {
          key: 'spec',
          label: state.specApproved ? 'Spec Gate' : 'Spec Draft',
          Icon: FileCheck,
          emphasis: state.specApproved ? 'approved' : 'neutral',
        },
        {
          key: 'plan',
          label: state.planApproved ? 'Plan Gate' : 'Plan Draft',
          Icon: FileText,
          emphasis: state.planApproved ? 'approved' : 'neutral',
        },
        { key: 'build', label: 'Implementer', Icon: Wand2 },
        { key: 'review', label: 'Review Loop', Icon: SearchCheck },
      ],
    },
    {
      key: 'superpowered-outer',
      radiusX: 286,
      radiusY: 126,
      tilt: 18,
      speed: 42,
      direction: -1,
      family: 'superpowered',
      nodes: [
        { key: 'verify', label: 'Verifier', Icon: ShieldCheck },
        { key: 'artifacts', label: 'Artifacts', Icon: Layers },
        {
          key: 'tasks',
          label: state.planTaskCount > 0 ? `${state.planTaskCount} Tasks` : 'Plan Tasks',
          Icon: Gauge,
          emphasis: state.planTaskCount > 0 ? 'approved' : 'neutral',
        },
        { key: 'memory', label: 'Memory', Icon: Network },
        { key: 'telemetry', label: 'Telemetry', Icon: Activity },
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
    tangent: angleDeg + tiltDeg + 90,
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
    const cutoff = Date.now() - 16000
    return (logs?.items ?? []).some((item) => {
      const eventType = String(item.event_type ?? '').toLowerCase()
      const ts = Date.parse(String(item.timestamp ?? ''))
      const recentEnough = Number.isFinite(ts) ? ts >= cutoff : false
      return recentEnough && (eventType.includes('task_') || eventType.includes('module_error') || eventType.includes('workflow_'))
    })
  }, [logs])

  const mode = visualState.mode
  const isActive = visualState.active || recentRuntimeActivity
  const rings = useMemo(
    () => [...buildLightningRings(), ...buildSuperpoweredRings(visualState)],
    [visualState],
  )
  const centerStatus = mode === 'superpowered'
    ? (data?.subagents_enabled ? 'review loop armed' : 'subagents offline')
    : 'rapid path'
  const centerMeta = mode === 'superpowered'
    ? `${visualState.specApproved ? 'spec' : 'draft'} / ${visualState.planApproved ? 'plan' : 'awaiting plan'}`
    : (data?.model_connected === false ? 'model offline' : 'model linked')
  const CenterIcon = mode === 'superpowered' ? Spline : Binary

  return (
    <div className={`${styles.root} ${styles[`mode-${mode}`]} ${isActive ? styles.rootActive : ''}`} aria-hidden>
      <div className={styles.fieldGlow} />
      <div className={`${styles.heatWake} ${isActive ? styles.heatWakeActive : ''}`} />

      {rings.map((ring) => (
        <div
          key={ring.key}
          className={`${styles.ringShell} ${styles[`family-${ring.family}`]}`}
        >
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
                <div
                  className={`${styles.nodeTrail} ${isActive ? styles.nodeTrailActive : ''}`}
                  style={{ transform: `translate(-50%, -50%) rotate(${point.tangent}deg)` }}
                />
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
          <div className={styles.coreBadge}>
            <CenterIcon size={22} strokeWidth={1.9} />
          </div>
          <span className={styles.coreEyebrow}>{mode}</span>
          <p className={styles.coreTitle}>Orchestrator</p>
          <p className={styles.coreStatus}>{centerStatus}</p>
          <p className={styles.coreMeta}>{centerMeta}</p>
        </div>
      </div>
    </div>
  )
}
