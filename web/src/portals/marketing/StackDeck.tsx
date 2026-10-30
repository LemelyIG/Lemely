/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import { ArrowRight } from '@phosphor-icons/react'
import { prefersReducedMotion } from '@/lib/celebration'
import './stack-deck.css'

/** Mobile card stack from the reference: the top card follows the finger,
 * a flick or tap throws it and the next card rises. Every card stays in the
 * document; only the top one is exposed to assistive tech. */
export function StackDeck({
  label,
  children,
  className = '',
  controls = 'dots',
  tone = 'light',
}: {
  label: string
  children: ReactNode[]
  className?: string
  /** `dots`: dots, count and a next button below. `label`: a count row above. */
  controls?: 'dots' | 'label'
  tone?: 'light' | 'dark'
}) {
  const n = children.length
  const [index, setIndex] = useState(0)
  const [tick, setTick] = useState(0)
  const [dx, setDx] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [leaving, setLeaving] = useState(0)
  const [seen, setSeen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const gesture = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const timer = useRef(0)

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

  const settle = (delta: number) => {
    setIndex((value) => (value + delta + n) % n)
    setTick((value) => value + 1)
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
    gesture.current = { x: event.clientX, y: event.clientY, moved: false }
    setDragging(true)
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
    setDx(moveX)
  }
  const onUp = () => {
    const current = gesture.current
    gesture.current = null
    if (!current) return
    if (Math.abs(dx) > 70) throwTop(Math.sign(dx))
    else if (!current.moved) throwTop(-1)
    else {
      setDragging(false)
      setDx(0)
    }
  }
  const onKey = (event: KeyboardEvent) => {
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

  const count = (
    <span role="status" aria-label="Slide position" className="stack-count">
      {index + 1} / {n}
    </span>
  )
  return (
    <div
      ref={root}
      role="region"
      aria-roledescription="carousel"
      aria-label={label}
      className={`brand-stack ${className}`}
      data-tone={tone}
      data-controls={controls}
      data-seen={seen}
    >
      {controls === 'label' && (
        <div className="stack-label-row">
          <span>SWIPE OR TAP</span>
          {count}
        </div>
      )}
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
          setDx(0)
        }}
        onKeyDown={onKey}
      >
        {children.map((child, k) => {
          const position = (k - index + n) % n
          const top = position === 0
          const style = top
            ? leaving
              ? {
                  transform: `translateX(${leaving * 420}px) rotate(${leaving * 14}deg)`,
                  opacity: 0,
                  transition: 'transform .28s ease-in, opacity .28s',
                }
              : {
                  transform: `translateX(${dx}px) rotate(${(dx / 22).toFixed(2)}deg)`,
                  transition: dragging ? 'none' : undefined,
                }
            : {
                transform: `translateY(${position * 11}px) scale(${1 - position * 0.045})`,
                opacity: position > 2 ? 0 : 1,
              }
          return (
            <div
              key={k}
              className="stack-card"
              data-top={top}
              aria-hidden={top ? undefined : true}
              inert={!top}
              aria-label={`${k + 1} of ${n}`}
              role="group"
              style={{ zIndex: n - position, ...style }}
            >
              <div key={top ? `on-${tick}` : 'off'} className="stack-card-body">
                {child}
              </div>
            </div>
          )
        })}
      </div>
      {controls === 'dots' && (
        <div className="stack-controls">
          <div className="stack-dots" aria-hidden="true">
            {children.map((_, k) => (
              <span key={k} data-active={k === index} />
            ))}
          </div>
          <span className="stack-count-text">{count} · SWIPE</span>
          <button
            type="button"
            className="stack-next"
            aria-label="Next card"
            onClick={() => {
              settle(1)
              const top = root.current?.getBoundingClientRect().top ?? 100
              // Keep the new card's heading clear of the sticky header.
              if (top < 80)
                window.scrollBy({ top: top - 88, behavior: 'instant' })
            }}
          >
            <ArrowRight aria-hidden="true" size={18} weight="bold" />
          </button>
        </div>
      )}
    </div>
  )
}
