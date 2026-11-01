/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, type ReactNode } from 'react'
import { useSceneMotion } from './useSceneMotion'
import motionData from './feature-motion-data.json'
import './art-motion.css'

type FeatureName = keyof typeof motionData
/** Timings and element paths are transcribed from the supplied Feature Art reference. */
export function FeatureMotion({
  name,
  children,
}: {
  name: FeatureName
  children: ReactNode
}) {
  const scene = useSceneMotion<HTMLDivElement>()
  const animations = useRef<Animation[]>([])
  const elapsed = useRef(0)
  useEffect(() => {
    const root = scene.ref.current?.querySelector('.brand-art')
    if (!root || scene.reducedMotion) return
    const restore: (() => void)[] = []
    animations.current = []
    for (const item of motionData[name]) {
      const el = root.querySelector<HTMLElement>(item.selector)
      if (!el) continue
      const original = el.getAttribute('style')
      const text = el.textContent
      restore.push(() => {
        if (original !== null) el.setAttribute('style', original)
        if (item.count) el.textContent = text
      })
      if (item.animation) {
        el.style.setProperty('--dx', item.dx)
        el.style.setProperty('--dy', item.dy)
        el.style.setProperty('--r', item.rotate)
        const kind = item.animation.split(' ')[0]
        const times = [...item.animation.matchAll(/(?:^|\s)([.\d]+)s/g)].map(
          (match) => Number(match[1]) * 1000,
        )
        const easing =
          item.animation.match(
            /cubic-bezier\([^)]+\)|ease-in-out|ease-out|ease-in|linear|ease/,
          )?.[0] ?? 'ease'
        const frames: Record<string, Keyframe[]> = {
          faDraw: [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }],
          faPop: [
            { transform: 'scale(0)' },
            { transform: 'scale(1.2)', offset: 0.6 },
            { transform: 'scale(1)' },
          ],
          faGrow: [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
          faUp: [
            { opacity: 0, transform: 'translateY(10px)' },
            { opacity: 1, transform: 'translateY(0)' },
          ],
          faSlot: [
            { transform: 'translateY(0)', offset: 0 },
            { transform: 'translateY(0)', offset: 0.3 },
            { transform: 'translateY(-104px)', offset: 0.55 },
            { transform: 'translateY(-104px)', offset: 0.7 },
            { transform: 'translateY(-208px)', offset: 0.95 },
            { transform: 'translateY(-208px)', offset: 1 },
          ],
          faMagnet: [
            {
              transform: `translate(${item.dx},${item.dy}) rotate(${item.rotate})`,
              opacity: 0,
            },
            { opacity: 1, offset: 0.25 },
            { transform: 'translate(0,0) scale(1.06)', offset: 0.75 },
            { transform: 'translate(0,0) scale(1)', opacity: 1 },
          ],
          faFlame: [
            { transform: 'scale(1,1)' },
            { transform: 'scale(.92,1.1)' },
            { transform: 'scale(1,1)' },
          ],
        }
        const animation = el.animate(frames[kind], {
          duration: times[0],
          delay: times[1] ?? 0,
          easing,
          fill: 'both',
          iterations: item.animation.includes('infinite') ? Infinity : 1,
        })
        animation.pause()
        animations.current.push(animation)
      }
    }
    return () => {
      animations.current.forEach((a) => a.cancel())
      animations.current = []
      restore.forEach((fn) => fn())
    }
  }, [name, scene.reducedMotion, scene.ref])
  useEffect(() => {
    // Finished one-shots stay at their final frame: play() or pause()+play() on one rewinds it.
    animations.current.forEach((a) => {
      if (a.playState === 'finished') return
      if (scene.enabled) a.play()
      else a.pause()
    })
    if (!scene.enabled) return
    const root = scene.ref.current?.querySelector('.brand-art')
    if (!root) return
    const counters = motionData[name]
      .filter((item) => item.count)
      .map((item) => ({ ...item, el: root.querySelector(item.selector) }))
    let frame = 0,
      previous = 0
    const count = (now: number) => {
      if (previous) elapsed.current += now - previous
      previous = now
      const progress = Math.min(1, elapsed.current / 1200)
      for (const item of counters)
        if (item.el)
          item.el.textContent =
            item.prefix +
            Math.round(
              Number(item.count) * (1 - (1 - progress) ** 3),
            ).toLocaleString() +
            item.suffix
      if (progress < 1) frame = requestAnimationFrame(count)
    }
    frame = requestAnimationFrame(count)
    return () => {
      cancelAnimationFrame(frame)
      animations.current.forEach((a) => {
        if (a.playState !== 'finished') a.pause()
      })
    }
  }, [name, scene.enabled, scene.ref])
  return (
    <div
      ref={scene.ref}
      data-art-scene={name}
      data-motion={scene.enabled ? 'running' : 'static'}
    >
      {children}
    </div>
  )
}
