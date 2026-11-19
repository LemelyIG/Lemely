/* Hallmark · pre-emit critique: P5 H4 E4 S4 R4 V3 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"
import { nativeHaptic } from "@/lib/haptics"
import { readPlatform } from "@/lib/platform"
import { bodyDragIntent, releaseVelocity, sheetRelease, trimSamples, type Detent, type PointerSample } from "@/lib/gestures/sheetMath"
import { PHONE_MEDIA } from "@/lib/useNativeFrame"
import { cn } from "@/lib/utils"

/*
 * The native frame's bottom sheet surface (brief §3.3). Presentation and
 * gesture only: the caller keeps the dialog contract (role, aria-modal,
 * label, focus trap, Escape, history) on the props it spreads here. Drag
 * starts on [data-sheet-drag-region] (grabber + header) and, once the body
 * sits at its top, on a downward move that starts in [data-sheet-body]
 * (user decision, 2026-11-13): an upward move or a scrolled body stays the
 * body's own scroll. A press on a row or button in the body may start that
 * drag too once it has moved past the slop, and the click that follows a drag
 * is swallowed so the row does not also fire. Fields (input, select, textarea)
 * never start one, and neither do the controls inside the grabber header.
 */
export interface BottomSheetSurfaceProps extends HTMLAttributes<HTMLDivElement> {
  detents?: readonly Detent[]
  initialDetent?: Detent
  dismissible?: boolean
  onDismiss: () => void
  closing?: boolean
  header?: ReactNode
  /** Classes for the scrolling body, where content gets its inset (the surface itself has none). */
  bodyClassName?: string
  children: ReactNode
}

export function SheetGrabber() {
  return <span aria-hidden="true" className="lm-sheet-grabber" />
}

/** iOS: while any sheet sits at the large detent, the page behind scales back.
 * It pivots on the top of what the reader sees: `lockScroll` pins the body at
 * `top: -scrollY`, so the scroll offset is read from there when it is locked. */
export function useSheetScaleBack(active: boolean): void {
  useEffect(() => {
    if (!active || readPlatform() !== "ios" || !window.matchMedia(PHONE_MEDIA).matches) return
    const root = document.documentElement
    const body = document.body.style
    const scrollY = body.position === "fixed" ? -parseFloat(body.top || "0") : window.scrollY
    root.style.setProperty("--native-sheet-sy", `${scrollY}px`)
    const depth = Number(root.dataset.sheetDepth ?? 0) + 1
    root.dataset.sheetDepth = String(depth)
    return () => {
      const next = Number(root.dataset.sheetDepth ?? 1) - 1
      if (next > 0) root.dataset.sheetDepth = String(next)
      else {
        delete root.dataset.sheetDepth
        root.style.removeProperty("--native-sheet-sy")
      }
    }
  }, [active])
}

/** iOS ignores interactive-widget: lift the sheet by the keyboard's height. */
export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const sync = () => setInset(Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)))
    sync()
    vv.addEventListener("resize", sync)
    vv.addEventListener("scroll", sync)
    return () => {
      vv.removeEventListener("resize", sync)
      vv.removeEventListener("scroll", sync)
    }
  }, [])
  return inset
}

interface DragState {
  id: number
  y: number
  samples: PointerSample[]
  /** The press began on a row, link or button, so its click must be swallowed if it turns into a drag. */
  onControl?: boolean
  /** A vertical scroller between the press and the sheet body: while it is scrolled down, a downward move scrolls it. */
  inner?: HTMLElement | null
}

/** The nearest vertically scrollable ancestor of `target` that sits inside `body`, if any. */
function innerScroller(target: Element, body: Element): HTMLElement | null {
  for (let el: Element | null = target; el && el !== body; el = el.parentElement) {
    if (!(el instanceof HTMLElement) || el.scrollHeight <= el.clientHeight) continue
    const overflow = getComputedStyle(el).overflowY
    if (overflow === "auto" || overflow === "scroll") return el
  }
  return null
}

/** Elements inside the drag region that keep their own click: header buttons, links, fields. */
const INTERACTIVE = "button, a, input, select, textarea, [role=button]"
/** Fields never start a sheet drag, wherever they sit: a press there is a caret or a slider move. */
const FIELD = "input, select, textarea, [role=slider]"

export const BottomSheetSurface = forwardRef<HTMLDivElement, BottomSheetSurfaceProps>(function BottomSheetSurface(
  {
    detents = ["content"],
    initialDetent,
    dismissible = true,
    onDismiss,
    closing = false,
    header,
    bodyClassName,
    children,
    className,
    style,
    onPointerDown: callerDown,
    onPointerMove: callerMove,
    onPointerUp: callerUp,
    onPointerCancel: callerCancel,
    onClickCapture: callerClickCapture,
    ...panel
  },
  ref,
) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const setRef = useCallback(
    (node: HTMLDivElement | null) => {
      panelRef.current = node
      if (typeof ref === "function") ref(node)
      else if (ref) ref.current = node
    },
    [ref],
  )
  const [detent, setDetent] = useState<Detent>(initialDetent ?? detents[detents.length - 1])
  const keyboard = useKeyboardInset()
  useSheetScaleBack(!closing && detent === "large")
  const drag = useRef<DragState | null>(null)
  /** A press in the body that has not yet shown whether it is a drag or a scroll. */
  const pending = useRef<DragState | null>(null)
  /** Set when a drag that began on a row or button ends: the click that follows must not fire it. */
  const swallowClick = useRef(false)
  const swallowTimer = useRef<number | undefined>(undefined)
  /** The swallow's 100ms window is open: a stray pointer end (the cancel a dismissal can cause) must not close it early. */
  const swallowArmed = useRef(false)
  useEffect(() => () => window.clearTimeout(swallowTimer.current), [])

  // Touch: once a body press has become a drag, the browser must not also pan the body.
  useEffect(() => {
    const panel = panelRef.current
    if (!panel) return
    const stop = (event: TouchEvent) => {
      if (drag.current && event.cancelable) event.preventDefault()
    }
    panel.addEventListener("touchmove", stop, { passive: false })
    return () => panel.removeEventListener("touchmove", stop)
  }, [])

  function beginDrag(d: DragState, el: HTMLElement): void {
    drag.current = d
    // While the finger is down the sheet follows it with no transition (preview drops is-sheet-snapping).
    panelRef.current?.setAttribute("data-dragging", "")
    el.setPointerCapture(d.id)
  }

  function onPointerDown(e: ReactPointerEvent<HTMLDivElement>): void {
    callerDown?.(e)
    const target = e.target as Element
    const inRegion = target.closest("[data-sheet-drag-region]")
    if (e.button > 0 || target.closest(FIELD) || (inRegion && target.closest(INTERACTIVE))) return
    if (!dismissible && detents.length < 2) return
    const start: DragState = { id: e.pointerId, y: e.clientY, samples: [[e.timeStamp, e.clientY]], onControl: !!target.closest(INTERACTIVE) }
    if (target.closest("[data-sheet-drag-region]")) beginDrag(start, e.currentTarget)
    else {
      const body = target.closest("[data-sheet-body]")
      if (body) pending.current = { ...start, inner: innerScroller(target, body) }
    }
  }
  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>): void {
    callerMove?.(e)
    const p = pending.current
    if (p && p.id === e.pointerId) {
      const body = panelRef.current?.querySelector<HTMLElement>("[data-sheet-body]")
      const intent = bodyDragIntent({ scrollTop: Math.max(body?.scrollTop ?? 0, p.inner?.scrollTop ?? 0), dy: e.clientY - p.y })
      if (intent === "scroll") pending.current = null
      else if (intent === "drag") {
        pending.current = null
        // A press that began on a row or button must not click when the finger lifts.
        if (p.onControl) swallowClick.current = true
        // The sheet starts from where the finger is now, so it does not jump by the slop.
        beginDrag({ id: p.id, y: e.clientY, samples: [[e.timeStamp, e.clientY]], onControl: p.onControl }, e.currentTarget)
      }
    }
    const d = drag.current
    if (!d || d.id !== e.pointerId || !panelRef.current) return
    d.samples = [...trimSamples(d.samples, e.timeStamp), [e.timeStamp, e.clientY]]
    panelRef.current.style.translate = `0 ${Math.max(e.clientY - d.y, -24)}px`
  }
  function endDrag(e: ReactPointerEvent<HTMLDivElement>): void {
    if (pending.current?.id === e.pointerId) pending.current = null
    const d = drag.current
    if (!d || d.id !== e.pointerId) {
      if (!swallowArmed.current) swallowClick.current = false
      return
    }
    drag.current = null
    // The click, if the browser sends one, arrives right after this pointerup. Armed after the
    // decision below: a dismissal clicks the sheet's own hidden Close, and that click must pass.
    const armSwallow = () => {
      if (!swallowClick.current) return
      window.clearTimeout(swallowTimer.current)
      swallowArmed.current = true
      swallowTimer.current = window.setTimeout(() => {
        swallowClick.current = false
        swallowArmed.current = false
      }, 100)
    }
    const el = panelRef.current
    if (!el) {
      armSwallow()
      return
    }
    el.removeAttribute("data-dragging")
    const dy = e.clientY - d.y
    const velocity = releaseVelocity(d.samples, e.timeStamp, e.clientY)
    const decision = sheetRelease({ dy, velocity, height: el.offsetHeight, detent, detents, dismissible })
    if (decision.kind === "dismiss") {
      // The exit slides out from where the finger left the sheet: the translate stays.
      swallowClick.current = false
      onDismiss()
      swallowClick.current = d.onControl === true
      armSwallow()
      return
    }
    el.style.translate = ""
    if (decision.detent !== detent) {
      setDetent(decision.detent)
      nativeHaptic("tap")
    }
    armSwallow()
  }
  function onPointerUp(e: ReactPointerEvent<HTMLDivElement>): void {
    callerUp?.(e)
    endDrag(e)
  }
  function onClickCapture(e: ReactMouseEvent<HTMLDivElement>): void {
    if (swallowClick.current) {
      swallowClick.current = false
      swallowArmed.current = false
      e.preventDefault()
      e.stopPropagation()
      return
    }
    callerClickCapture?.(e)
  }
  function onPointerCancel(e: ReactPointerEvent<HTMLDivElement>): void {
    callerCancel?.(e)
    endDrag(e)
  }

  return (
    <div
      {...panel}
      ref={setRef}
      data-detent={detent}
      data-closing={closing || undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onClickCapture={onClickCapture}
      // A link's native drag-and-drop (a mouse or a stylus) would take the pointer away mid-drag; nothing in a sheet is draggable.
      onDragStart={(event) => event.preventDefault()}
      style={{ ...style, ["--lm-keyboard-inset" as string]: `${keyboard}px` }}
      className={cn("lm-sheet", className)}
    >
      {/* Without a grabber (a non-dismissible dialog) the title would sit at the sheet's edge:
          `data-no-grabber` restores the Material 3 dialog's 24px top padding. */}
      <div
        data-sheet-drag-region
        data-no-grabber={dismissible || detents.length > 1 ? undefined : ""}
        className="flex flex-col items-center select-none"
      >
        {dismissible || detents.length > 1 ? <SheetGrabber /> : null}
        {header}
      </div>
      <div data-sheet-body className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain lm-scroll", bodyClassName)}>
        {children}
      </div>
    </div>
  )
})
