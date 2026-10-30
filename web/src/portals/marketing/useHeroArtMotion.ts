import { useEffect, useRef } from 'react'
import { useSceneMotion } from './useSceneMotion'
import './art-motion.css'

const points = [
  [90, 320],
  [210, 250],
  [330, 250],
  [450, 170],
  [570, 90],
]
const grades = ['C', 'B', 'B', 'A', 'A*']
const gradeTokens = [7, 8, 8, 9, 10]
/** Binny follows the workshop's 9.6 second five-paper journey. */
export function useHeroArtMotion() {
  const scene = useSceneMotion<HTMLElement>()
  const clock = useRef(0)
  // The journey plays once and then holds its finished chart, like the reference's settled state.
  const done = useRef(false)
  useEffect(() => {
    const root = scene.ref.current
    if (!root) return
    const q = (key: string) =>
      root.querySelector<SVGElement>(`[data-hc="${key}"]`)
    const clip = q('clip'),
      binny = q('binny'),
      grade = root.querySelector<HTMLElement>('.brand-predicted b')
    if (!clip || !binny || !grade) return
    const snapshots = [...root.querySelectorAll<SVGElement>('[data-hc]')].map(
      (el) => ({
        el,
        transform: el.getAttribute('transform'),
        opacity: el.getAttribute('opacity'),
        style: el.getAttribute('style'),
      }),
    )
    const set = (key: string, attr: string, value: string | number) =>
      q(key)?.setAttribute(attr, String(value))
    let raf = 0,
      previous = 0,
      celebration = -Infinity,
      hover = -Infinity
    let mouse: [number, number] | null = null
    const cheer = () => {
      celebration = clock.current
      hover = clock.current
      if (!scene.enabled || done.current) {
        set('lvl', 'opacity', 1)
        for (const name of ['happy', 'open']) {
          const el = q(name)
          if (el) el.style.display = ''
        }
        for (const name of ['eyes', 'smile']) {
          const el = q(name)
          if (el) el.style.display = 'none'
        }
      }
    }
    const enter = () => {
      hover = clock.current
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        cheer()
      }
    }
    const move = (event: PointerEvent) => {
      mouse = [event.clientX, event.clientY]
    }
    const restore = () => {
      snapshots.forEach(({ el, transform, opacity, style }) => {
        for (const [name, value] of [
          ['transform', transform],
          ['opacity', opacity],
          ['style', style],
        ]) {
          if (value === null) el.removeAttribute(name!)
          else el.setAttribute(name!, value!)
        }
      })
      clip.setAttribute('width', '640')
      grade.textContent = 'A*'
      grade.style.removeProperty('background-color')
    }
    const frame = (now: number) => {
      if (previous) clock.current += Math.min(now - previous, 80)
      previous = now
      if (clock.current >= 9600) {
        done.current = true
        restore()
        return
      }
      const t = (clock.current / 1000) % 9.6
      const index = Math.max(0, Math.min(4, Math.floor((t - 0.8) / 1.5)))
      let position = index,
        arc =
          t < 0.8
            ? (1 - Math.min(1, Math.max(0, (t - 0.2) / 0.6)) ** 2) * 120
            : 0
      let stretch = 0
      for (let i = 1; i < 5; i++) {
        const f = (t - (0.8 + i * 1.5 - 0.6)) / 0.6
        if (f >= 0 && f < 1) {
          const ease = f < 0.5 ? 4 * f ** 3 : 1 - (-2 * f + 2) ** 3 / 2
          position = i - 1 + ease
          arc = Math.sin(Math.PI * f) * 62
          stretch = 0.08
        }
      }
      const a = Math.floor(position),
        b = Math.min(4, a + 1),
        fraction = position - a
      const x = points[a][0] + (points[b][0] - points[a][0]) * fraction
      const y = points[a][1] + (points[b][1] - points[a][1]) * fraction - arc
      const levelTime = (clock.current - celebration) / 1000
      const hop =
        levelTime < 0.7 ? Math.sin((Math.PI * levelTime) / 0.7) * 46 : 0
      binny.setAttribute('transform', `translate(${x - 42} ${y - 90 - hop})`)
      set(
        'squash',
        'transform',
        `translate(42 90) scale(${1 - stretch} ${1 + stretch}) translate(-42 -90)`,
      )
      clip.setAttribute('width', String(Math.max(90, x)))
      root.querySelectorAll('[data-hc="pt"]').forEach((el, i) => {
        const f = Math.max(0, Math.min(1, (t - (0.8 + i * 1.5)) / 0.4))
        const scale = f === 1 ? 1 : f * (1 + Math.sin(f * Math.PI) * 0.35)
        el.setAttribute(
          'transform',
          `translate(${points[i][0]} ${points[i][1]}) scale(${scale})`,
        )
      })
      grade.textContent = grades[index]
      grade.style.backgroundColor = `var(--brand-art-${gradeTokens[index]})`
      const ds = t - 6.8,
        happy =
          (ds >= 0 && ds < 1.6) ||
          clock.current - hover < 1400 ||
          levelTime < 1.8
      set(
        'spark',
        'opacity',
        ds >= 0 && ds < 1.4 ? Math.sin((Math.PI * ds) / 1.4) : 0,
      )
      set(
        'spark',
        'transform',
        `translate(570 40) scale(${0.6 + Math.max(0, Math.min(1, ds / 1.4)) * 0.6})`,
      )
      set(
        'lvl',
        'opacity',
        levelTime < 1.8
          ? Math.min(1, levelTime / 0.15, (1.8 - levelTime) / 0.4)
          : 0,
      )
      set(
        'lvl',
        'transform',
        `translate(0 ${levelTime < 1.8 ? -Math.min(levelTime, 0.5) * 16 : 0})`,
      )
      for (const name of ['happy', 'open']) {
        const el = q(name)
        if (el) el.style.display = happy ? '' : 'none'
      }
      for (const name of ['eyes', 'smile']) {
        const el = q(name)
        if (el) el.style.display = happy ? 'none' : ''
      }
      const wag =
        Math.sin(clock.current / (happy ? 70 : 400)) * (happy ? 14 : 3)
      set('earL', 'transform', `rotate(${-6 - wag} 75 100)`)
      set('earR', 'transform', `rotate(${6 + wag} 125 100)`)
      set(
        'eyes',
        'transform',
        `translate(0 140) scale(1 ${clock.current % 3600 > 3450 ? 0.1 : 1}) translate(0 -140)`,
      )
      if (mouse) {
        const rect = binny.getBoundingClientRect(),
          dx = mouse[0] - rect.left - rect.width / 2,
          dy = mouse[1] - rect.top - rect.height / 2,
          distance = Math.hypot(dx, dy) || 1
        set(
          'pupils',
          'transform',
          `translate(${(dx / distance) * 4} ${(dy / distance) * 4})`,
        )
      }
      raf = requestAnimationFrame(frame)
    }
    if (scene.enabled && !done.current) {
      raf = requestAnimationFrame(frame)
      root.addEventListener('pointermove', move)
    }
    binny.addEventListener('click', cheer)
    binny.addEventListener('pointerenter', enter)
    binny.addEventListener('keydown', key)
    return () => {
      cancelAnimationFrame(raf)
      binny.removeEventListener('click', cheer)
      binny.removeEventListener('pointerenter', enter)
      binny.removeEventListener('keydown', key)
      root.removeEventListener('pointermove', move)
      restore()
    }
  }, [scene.enabled, scene.ref])
  return scene
}
