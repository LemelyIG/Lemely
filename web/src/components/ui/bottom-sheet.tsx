import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"
import { haptic } from "@/lib/haptics"
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
 * body's own scroll, and pressing a control never starts a drag.
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
}

/** Elements inside the drag region that keep their own click: header buttons, links, fields. */
const INTERACTIVE = "button, a, input, select, textarea, [role=button]"

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
    if (e.button > 0 || target.closest(INTERACTIVE)) return
    if (!dismissible && detents.length < 2) return
    const start: DragState = { id: e.pointerId, y: e.clientY, samples: [[e.timeStamp, e.clientY]] }
    if (target.closest("[data-sheet-drag-region]")) beginDrag(start, e.currentTarget)
    else if (target.closest("[data-sheet-body]")) pending.current = start
  }
  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>): void {
    callerMove?.(e)
    const p = pending.current
    if (p && p.id === e.pointerId) {
      const body = panelRef.current?.querySelector<HTMLElement>("[data-sheet-body]")
      const intent = bodyDragIntent({ scrollTop: body?.scrollTop ?? 0, dy: e.clientY - p.y })
      if (intent === "scroll") pending.current = null
      else if (intent === "drag") {
        pending.current = null
        // The sheet starts from where the finger is now, so it does not jump by the slop.
        beginDrag({ id: p.id, y: e.clientY, samples: [[e.timeStamp, e.clientY]] }, e.currentTarget)
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
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    const el = panelRef.current
    if (!el) return
    el.removeAttribute("data-dragging")
    const dy = e.clientY - d.y
    const velocity = releaseVelocity(d.samples, e.timeStamp, e.clientY)
    const decision = sheetRelease({ dy, velocity, height: el.offsetHeight, detent, detents, dismissible })
    if (decision.kind === "dismiss") {
      // The exit slides out from where the finger left the sheet: the translate stays.
      onDismiss()
      return
    }
    el.style.translate = ""
    if (decision.detent !== detent) {
      setDetent(decision.detent)
      if (readPlatform() === "android") haptic("tap")
    }
  }
  function onPointerUp(e: ReactPointerEvent<HTMLDivElement>): void {
    callerUp?.(e)
    endDrag(e)
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
      style={{ ...style, ["--lm-keyboard-inset" as string]: `${keyboard}px` }}
      className={cn("lm-sheet", className)}
    >
      <div data-sheet-drag-region className="flex flex-col items-center select-none">
        {dismissible || detents.length > 1 ? <SheetGrabber /> : null}
        {header}
      </div>
      <div data-sheet-body className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain lm-scroll", bodyClassName)}>
        {children}
      </div>
    </div>
  )
})
