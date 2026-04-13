import { useEffect, useRef } from 'react'
import { Camera, Geometry, Mesh, Program, Renderer } from 'ogl'
import styles from './HeartbeatTrail.module.css'

const RED_PALETTE = ['#ff2d2d', '#ff4a4a', '#ff7777']

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace(/^#/, '')
  const normalized = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean
  const num = Number.parseInt(normalized, 16)
  return [((num >> 16) & 255) / 255, ((num >> 8) & 255) / 255, (num & 255) / 255]
}

const vertex = /* glsl */ `
  attribute vec3 position;
  attribute vec4 random;
  attribute vec3 color;

  uniform mat4 modelMatrix;
  uniform mat4 viewMatrix;
  uniform mat4 projectionMatrix;
  uniform float uTime;
  uniform float uSpread;
  uniform float uBaseSize;
  uniform float uSizeRandomness;

  varying vec4 vRandom;
  varying vec3 vColor;

  void main() {
    vRandom = random;
    vColor = color;

    vec3 pos = position * uSpread;
    pos.z *= 10.0;

    vec4 mPos = modelMatrix * vec4(pos, 1.0);
    float t = uTime;
    mPos.x += sin(t * random.z + 6.28 * random.w) * mix(0.1, 1.4, random.x);
    mPos.y += sin(t * random.y + 6.28 * random.x) * mix(0.1, 1.4, random.w);
    mPos.z += sin(t * random.w + 6.28 * random.y) * mix(0.1, 1.4, random.z);

    vec4 mvPos = viewMatrix * mPos;
    gl_PointSize = (uBaseSize * (1.0 + uSizeRandomness * (random.x - 0.5))) / length(mvPos.xyz);
    gl_Position = projectionMatrix * mvPos;
  }
`

const fragment = /* glsl */ `
  precision highp float;

  uniform float uTime;
  varying vec4 vRandom;
  varying vec3 vColor;

  void main() {
    vec2 uv = gl_PointCoord.xy;
    float d = length(uv - vec2(0.5));
    float circle = smoothstep(0.5, 0.35, d);
    vec3 glow = vColor + 0.18 * sin(uv.yxx + uTime + vRandom.y * 6.28);
    gl_FragColor = vec4(glow, circle * 0.88);
  }
`

export function HeartbeatTrail() {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }

    const renderer = new Renderer({
      dpr: Math.min(window.devicePixelRatio || 1, 1.5),
      depth: false,
      alpha: true,
    })
    const gl = renderer.gl
    gl.clearColor(0, 0, 0, 0)
    container.appendChild(gl.canvas)

    const camera = new Camera(gl, { fov: 15 })
    camera.position.set(0, 0, 20)

    const resize = () => {
      const width = container.clientWidth
      const height = container.clientHeight
      renderer.setSize(width, height)
      camera.perspective({ aspect: gl.canvas.width / gl.canvas.height })
    }
    window.addEventListener('resize', resize)
    resize()

    const count = 260
    const positions = new Float32Array(count * 3)
    const randoms = new Float32Array(count * 4)
    const colors = new Float32Array(count * 3)

    for (let i = 0; i < count; i += 1) {
      let x = 0
      let y = 0
      let z = 0
      let len = 0
      do {
        x = Math.random() * 2 - 1
        y = Math.random() * 2 - 1
        z = Math.random() * 2 - 1
        len = x * x + y * y + z * z
      } while (len > 1 || len === 0)

      const r = Math.cbrt(Math.random())
      positions.set([x * r, y * r, z * r], i * 3)
      randoms.set([Math.random(), Math.random(), Math.random(), Math.random()], i * 4)
      colors.set(hexToRgb(RED_PALETTE[Math.floor(Math.random() * RED_PALETTE.length)]), i * 3)
    }

    const geometry = new Geometry(gl, {
      position: { size: 3, data: positions },
      random: { size: 4, data: randoms },
      color: { size: 3, data: colors },
    })

    const program = new Program(gl, {
      vertex,
      fragment,
      uniforms: {
        uTime: { value: 0 },
        uSpread: { value: 10 },
        uBaseSize: { value: 96 },
        uSizeRandomness: { value: 1 },
      },
      transparent: true,
      depthTest: false,
    })

    const particles = new Mesh(gl, { mode: gl.POINTS, geometry, program })

    let rafId = 0
    let last = performance.now()
    let elapsed = 0

    const update = (now: number) => {
      rafId = requestAnimationFrame(update)
      const delta = now - last
      last = now
      elapsed += delta * 0.09

      program.uniforms.uTime.value = elapsed * 0.001
      particles.rotation.x = Math.sin(elapsed * 0.0002) * 0.09
      particles.rotation.y = Math.cos(elapsed * 0.0005) * 0.14
      particles.rotation.z += 0.00075

      renderer.render({ scene: particles, camera })
    }

    rafId = requestAnimationFrame(update)

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener('resize', resize)
      if (container.contains(gl.canvas)) {
        container.removeChild(gl.canvas)
      }
    }
  }, [])

  return (
    <div className={styles.root} aria-hidden>
      <div ref={containerRef} className={styles.particlesContainer} />
    </div>
  )
}
