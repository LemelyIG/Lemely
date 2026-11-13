/*
 * Native frame press feedback (brief §3.5). One delegated listener for the
 * whole app; elements opt in with `.lm-press`. CSS does the drawing; this only
 * records the touch point (Android ripple) and the pressed flag.
 */
interface PressRect {
  left: number
  top: number
  width: number
  height: number
}

export function pressOrigin(rect: PressRect, x: number, y: number): { x: string; y: string; r: string } {
  const px = x - rect.left
  const py = y - rect.top
  const r = Math.ceil(Math.hypot(Math.max(px, rect.width - px), Math.max(py, rect.height - py)))
  return { x: `${px}px`, y: `${py}px`, r: `${r}px` }
}

const RELEASE_EVENTS = ["pointerup", "pointercancel", "pointerleave", "dragstart"] as const

export function installPressFeedback(root: Document | HTMLElement): () => void {
  let pressed: HTMLElement | null = null
  const release = (): void => {
    pressed?.removeAttribute("data-pressed")
    pressed = null
  }
  const down = (event: Event): void => {
    const e = event as PointerEvent
    const el = (e.target as Element | null)?.closest<HTMLElement>(".lm-press")
    if (!el || (el as HTMLButtonElement).disabled) return
    const o = pressOrigin(el.getBoundingClientRect(), e.clientX, e.clientY)
    el.style.setProperty("--lm-press-x", o.x)
    el.style.setProperty("--lm-press-y", o.y)
    el.style.setProperty("--lm-press-r", o.r)
    el.setAttribute("data-pressed", "")
    pressed = el
  }
  root.addEventListener("pointerdown", down, { passive: true })
  for (const type of RELEASE_EVENTS) root.addEventListener(type, release, { passive: true })
  return () => {
    root.removeEventListener("pointerdown", down)
    for (const type of RELEASE_EVENTS) root.removeEventListener(type, release)
  }
}
