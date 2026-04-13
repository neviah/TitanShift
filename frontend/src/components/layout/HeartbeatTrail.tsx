import styles from './HeartbeatTrail.module.css'

// One ECG beat as relative [x, y] points (baseline y=30, viewBox height=60, beat width=600)
const BEAT_REL: [number, number][] = [
  [0, 30], [150, 30],
  [170, 25], [185, 15], [200, 25], [215, 30], // P wave
  [240, 30],
  [248, 35], [258, 4], [268, 50], [278, 30],  // QRS complex
  [300, 30],
  [325, 22], [345, 14], [365, 22], [380, 30], // T wave
  [600, 30],                                   // flat tail to next beat
]

// 4 beats makes the SVG 200% viewport wide (seamless loop when scrolled by 50%)
const ECG_POINTS = Array.from({ length: 4 }, (_, i) =>
  BEAT_REL.map(([x, y]) => `${x + i * 600},${y}`).join(' ')
).join(' ')

export function HeartbeatTrail() {
  return (
    <div className={styles.root} aria-hidden>
      <svg
        className={styles.ecg}
        viewBox="0 0 2400 60"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id="hbGlow" x="-10%" y="-120%" width="120%" height="340%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feFlood floodColor="#ff2020" floodOpacity="0.6" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="glow" />
            <feMerge>
              <feMergeNode in="glow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <polyline
          points={ECG_POINTS}
          fill="none"
          stroke="#ff2d2d"
          strokeWidth="1.8"
          strokeLinejoin="round"
          filter="url(#hbGlow)"
        />
      </svg>
    </div>
  )
}
