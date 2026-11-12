/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import { ArrowRight, ArrowsLeftRight } from '@phosphor-icons/react'
import { prefersReducedMotion } from '@/lib/celebration'
import './stack-deck.css'

/** Drag feel: past COMMIT the card resists, and never travels beyond MAX. */
const COMMIT = 60
const MAX_DRAG = 140
const FLICK = 0.45 // px per ms
const HINT_DELAY = 800
const HINT_MS = 1300
/** The half-swipe hint plays once per deck per page view. */
const hinted = new Set<string>()

const rubber = (x: number) => {
  const a = Math.abs(x)
  if (a <= COMMIT) return x
  return Math.sign(x) * Math.min(MAX_DRAG, COMMIT + (a - COMMIT) * 0.4)
}

/** Mobile card stack from the reference: a cue row above (swipe cue, dots,
 * count, next) and a deep stack below. The top card follows the finger, a
 * flick or tap throws it and the next card rises. Every card stays in the
 * document; only the top one is exposed to assistive tech. */
export function StackDeck({
  label,
  children,
  className = '',
  tone = 'light',
}: {
  label: string
  children: ReactNode[]
  className?: string
  tone?: 'light' | 'dark'
}) {
  const n = children.length
  const [index, setIndex] = useState(0)
  const [tick, setTick] = useState(0)
  const [dx, setDx] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [leaving, setLeaving] = useState(0)
  const [seen, setSeen] = useState(false)
  const [hint, setHint] = useState(false)
  const [touched, setTouched] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const gesture = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const dxRef = useRef(0)
  const track = useRef({ x: 0, t: 0, v: 0 })
  const timer = useRef(0)
  const hintTimers = useRef<number[]>([])
  const interacted = useRef(false)

  useEffect(() => {
    const element = root.current
    if (!element || typeof IntersectionObserver === 'undefined') {
      setSeen(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true)
          observer.disconnect()
        }
      },
      { rootMargin: '0px 0px -20% 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const stopHint = () => {
    hintTimers.current.forEach((id) => window.clearTimeout(id))
    hintTimers.current = []
    setHint(false)
  }
  const interact = () => {
    interacted.current = true
    stopHint()
    setTouched(true)
  }

  // Half-swipe hint: after the first card's art has started, nudge the top
  // card toward the next one once, then settle.
  useEffect(() => {
    if (!seen || interacted.current || hinted.has(label)) return
    if (prefersReducedMotion()) return
    const start = window.setTimeout(() => {
      if (interacted.current || hinted.has(label)) return
      hinted.add(label)
      setHint(true)
      hintTimers.current.push(window.setTimeout(() => setHint(false), HINT_MS))
    }, HINT_DELAY)
    hintTimers.current.push(start)
    const onKeyDown = () => interact()
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      hintTimers.current.forEach((id) => window.clearTimeout(id))
      hintTimers.current = []
    }
  }, [seen, label])

  const settle = (delta: number) => {
    setIndex((value) => (value + delta + n) % n)
    setTick((value) => value + 1)
    dxRef.current = 0
    setDx(0)
    setLeaving(0)
  }
  const throwTop = (direction: number) => {
    setDragging(false)
    if (prefersReducedMotion()) {
      settle(1)
      return
    }
    setLeaving(direction)
    timer.current = window.setTimeout(() => settle(1), 260)
  }
  const onDown = (event: PointerEvent) => {
    if (leaving) return
    interact()
    gesture.current = { x: event.clientX, y: event.clientY, moved: false }
    track.current = { x: event.clientX, t: performance.now(), v: 0 }
    setDragging(true)
    dxRef.current = 0
    setDx(0)
  }
  const onMove = (event: PointerEvent) => {
    const current = gesture.current
    if (!current) return
    const moveX = event.clientX - current.x
    const moveY = event.clientY - current.y
    if (
      !current.moved &&
      Math.abs(moveY) > Math.abs(moveX) &&
      Math.abs(moveY) > 8
    ) {
      gesture.current = null
      setDragging(false)
      dxRef.current = 0
      setDx(0)
      return
    }
    if (Math.abs(moveX) > 6) {
      if (!current.moved) {
        try {
          event.currentTarget.setPointerCapture(event.pointerId)
        } catch {
          /* capture is an enhancement only */
        }
      }
      current.moved = true
    }
    const now = performance.now()
    const last = track.current
    if (now > last.t) {
      const instant = (event.clientX - last.x) / (now - last.t)
      track.current = { x: event.clientX, t: now, v: last.v * 0.5 + instant * 0.5 }
    }
    dxRef.current = moveX
    setDx(moveX)
  }
  const onUp = () => {
    const current = gesture.current
    gesture.current = null
    if (!current) return
    const moved = dxRef.current
    const { v, t } = track.current
    const fresh = performance.now() - t < 90
    const flick =
      fresh && Math.abs(v) > FLICK && Math.abs(moved) > 14 && Math.sign(v) === Math.sign(moved)
    if (Math.abs(moved) > COMMIT || flick) throwTop(Math.sign(moved))
    else if (!current.moved) throwTop(-1)
    else {
      setDragging(false)
      dxRef.current = 0
      setDx(0)
    }
  }
  const onKey = (event: KeyboardEvent) => {
    interact()
    if (
      event.key === 'ArrowRight' ||
      event.key === 'Enter' ||
      event.key === ' '
    ) {
      event.preventDefault()
      settle(1)
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      settle(-1)
    }
  }
  const next = () => {
    interact()
    settle(1)
    const top = root.current?.getBoundingClientRect().top ?? 100
    // Keep the new card's heading clear of the sticky header.
    if (top < 80) window.scrollBy({ top: top - 88, behavior: 'instant' })
  }

  const count = (
    <span role="status" aria-label="Slide position" className="stack-count">
      {index + 1} / {n}
    </span>
  )
  const dots = (
    <div className="stack-dots" aria-hidden="true">
      {children.map((_, k) => (
        <span key={k} data-active={k === index} />
      ))}
    </div>
  )
  const visual = rubber(dx)
  const progress = Math.min(1, Math.abs(visual) / 90)
  return (
    <div
      ref={root}
      role="region"
      aria-roledescription="carousel"
      aria-label={label}
      className={`brand-stack ${className}`}
      data-tone={tone}
      data-seen={seen}
      data-touched={touched}
      data-hint={hint}
    >
      <div className="stack-label-row">
        <span className="stack-cue">
          <ArrowsLeftRight aria-hidden="true" size={16} weight="bold" />
          SWIPE OR TAP
        </span>
        <div className="stack-label-meta">
          {dots}
          {count}
          <button
            type="button"
            className="stack-next"
            aria-label="Next card"
            onClick={next}
          >
            <ArrowRight aria-hidden="true" size={16} weight="bold" />
          </button>
        </div>
      </div>
      <div
        role="group"
        aria-label={`${label} cards`}
        tabIndex={0}
        className="stack-viewport"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={() => {
          gesture.current = null
          setDragging(false)
          dxRef.current = 0
          setDx(0)
        }}
        onKeyDown={onKey}
      >
        {children.map((child, k) => {
          const position = (k - index + n) % n
          const top = position === 0
          // Cards behind rise toward the front as the top card is dragged.
          const lift = position - (position >= 1 && !leaving ? progress : 0)
          const peek = lift <= 1 ? lift * 24 : 24 + (lift - 1) * 6
          const style = top
            ? leaving
              ? {
                  transform: `translateX(${leaving * 420}px) rotate(${leaving * 14}deg)`,
                  opacity: 0,
                  transition: 'transform .28s ease-in, opacity .28s',
                }
              : {
                  transform: `translateX(${visual}px) rotate(${(visual / 22).toFixed(2)}deg)`,
                  transition: dragging ? 'none' : undefined,
                }
            : {
                transform: `translate(${peek.toFixed(1)}px, ${(lift * 11).toFixed(1)}px) scale(${(1 - lift * 0.045).toFixed(4)})`,
                opacity: position > 2 ? 0 : 1,
                transition: dragging ? 'none' : undefined,
              }
          return (
            <div
              key={k}
              className="stack-card"
              data-top={top}
              data-next={position === 1}
              aria-hidden={top ? undefined : true}
              inert={!top}
              aria-label={`${k + 1} of ${n}`}
              role="group"
              style={{ ...({ '--stack-z': n - position } as CSSProperties), ...style }}
            >
              <div key={top ? `on-${tick}` : 'off'} className="stack-card-body">
                {child}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
