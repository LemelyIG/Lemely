/*
 * Native frame press feedback (brief §3.5). One delegated listener for the
 * whole app; elements opt in with `.lm-press`. CSS does the drawing; this only
 * records the touch point (Android ripple) and the pressed flag. Rows inside scrolling
 * content (`.lm-press-delay`) hold the flag back by `--native-press-delay`, so a scroll
 * that starts on a row never flashes it.
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

const DISABLED = '[aria-disabled="true"], :disabled'

/**
 * True when the press lands on something disabled. A disabled control carries
 * `pointer-events: none`, so the tap passes through to the pressable ancestor and
 * `target` is that ancestor: the descendant is found by its box instead.
 */
function pressIsDisabled(el: HTMLElement, target: Element, x: number, y: number): boolean {
  if (el.matches(DISABLED)) return true
  const hit = target.closest(DISABLED)
  if (hit && el.contains(hit)) return true
  for (const d of el.querySelectorAll(DISABLED)) {
    const r = d.getBoundingClientRect()
    if (x >= r.left && x <= r.left + r.width && y >= r.top && y <= r.top + r.height) return true
  }
  return false
}

const RELEASE_EVENTS = ["pointerup", "pointercancel", "dragstart"] as const
const DEFAULT_DELAY_MS = 100
/** Movement past this many px before the delay ends is a scroll, not a press. */
const SLOP_PX = 8
/** A tap released inside the delay still shows the highlight this long, as native does. */
const FLASH_MS = 100

function delayOf(el: HTMLElement): number {
  if (!el.matches(".lm-press-delay")) return 0
  if (typeof getComputedStyle !== "function") return DEFAULT_DELAY_MS
  const ms = parseFloat(getComputedStyle(el).getPropertyValue("--native-press-delay"))
  return Number.isFinite(ms) ? ms : DEFAULT_DELAY_MS
}

export function installPressFeedback(root: Document | HTMLElement): () => void {
  let pressed: HTMLElement | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: { x: number; y: number } | null = null
  let flash: { el: HTMLElement; timer: ReturnType<typeof setTimeout> } | null = null
  const endFlash = (): void => {
    if (!flash) return
    clearTimeout(flash.timer)
    flash.el.removeAttribute("data-pressed")
    flash = null
  }
  const abandon = (): void => {
    if (timer) clearTimeout(timer)
    timer = null
    pending = null
  }
  const release = (): void => {
    pressed?.removeAttribute("data-pressed")
    pressed = null
    abandon()
  }
  const up = (event: Event): void => {
    // Released before the delay ended: a tap. Flash the highlight briefly; a cancel never does.
    if (event.type === "pointerup" && pressed && pending) {
      const el = pressed
      abandon()
      pressed = null
      el.setAttribute("data-pressed", "")
      flash = { el, timer: setTimeout(endFlash, FLASH_MS) }
      return
    }
    release()
  }
  const move = (event: Event): void => {
    if (!pending) return
    const e = event as PointerEvent
    if (Math.hypot(e.clientX - pending.x, e.clientY - pending.y) > SLOP_PX) release()
  }
  const down = (event: Event): void => {
    const e = event as PointerEvent
    const target = e.target as Element | null
    const el = target?.closest<HTMLElement>(".lm-press")
    // A second pointer must not leave the first element stuck pressed.
    release()
    endFlash()
    if (!target || !el || pressIsDisabled(el, target, e.clientX, e.clientY)) return
    const o = pressOrigin(el.getBoundingClientRect(), e.clientX, e.clientY)
    el.style.setProperty("--lm-press-x", o.x)
    el.style.setProperty("--lm-press-y", o.y)
    el.style.setProperty("--lm-press-r", o.r)
    pressed = el
    const delay = delayOf(el)
    if (delay <= 0) {
      el.setAttribute("data-pressed", "")
      return
    }
    pending = { x: e.clientX, y: e.clientY }
    timer = setTimeout(() => {
      timer = null
      pending = null
      el.setAttribute("data-pressed", "")
    }, delay)
  }
  root.addEventListener("pointerdown", down, { passive: true })
  root.addEventListener("pointermove", move, { passive: true })
  for (const type of RELEASE_EVENTS) root.addEventListener(type, up, { passive: true })
  return () => {
    release()
    endFlash()
    root.removeEventListener("pointerdown", down)
    root.removeEventListener("pointermove", move)
    for (const type of RELEASE_EVENTS) root.removeEventListener(type, up)
  }
}
