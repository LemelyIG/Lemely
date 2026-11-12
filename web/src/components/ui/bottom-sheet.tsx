import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"
import { haptic } from "@/lib/haptics"
import { readPlatform } from "@/lib/platform"
import { sheetRelease, type Detent } from "@/lib/gestures/sheetMath"
import { cn } from "@/lib/utils"

/*
 * The native frame's bottom sheet surface (brief §3.3). Presentation and
 * gesture only: the caller keeps the dialog contract (role, aria-modal,
 * label, focus trap, Escape, history) on the props it spreads here. Drag
 * starts only on [data-sheet-drag-region] (grabber + header), so text in the
 * body stays selectable and inner scrolling stays native.
 */
export interface BottomSheetSurfaceProps extends HTMLAttributes<HTMLDivElement> {
  detents?: readonly Detent[]
  initialDetent?: Detent
  dismissible?: boolean
  onDismiss: () => void
  closing?: boolean
  header?: ReactNode
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
    if (!active || readPlatform() !== "ios") return
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
  t: number
  lastY: number
  lastT: number
}

export const BottomSheetSurface = forwardRef<HTMLDivElement, BottomSheetSurfaceProps>(function BottomSheetSurface(
  { detents = ["content"], initialDetent, dismissible = true, onDismiss, closing = false, header, children, className, style, ...panel },
  ref,
) {
  const panelRef = useRef<HTMLDivElement>(null)
  useImperativeHandle(ref, () => panelRef.current as HTMLDivElement)
  const [detent, setDetent] = useState<Detent>(initialDetent ?? detents[detents.length - 1])
  const keyboard = useKeyboardInset()
  useSheetScaleBack(!closing && detent === "large")
  const drag = useRef<DragState | null>(null)

  function onPointerDown(e: ReactPointerEvent<HTMLDivElement>): void {
    if (!(e.target as Element).closest("[data-sheet-drag-region]")) return
    if (!dismissible && detents.length < 2) return
    drag.current = { id: e.pointerId, y: e.clientY, t: e.timeStamp, lastY: e.clientY, lastT: e.timeStamp }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>): void {
    const d = drag.current
    if (!d || d.id !== e.pointerId || !panelRef.current) return
    const dy = e.clientY - d.y
    panelRef.current.style.translate = `0 ${Math.max(dy, -24)}px`
    d.lastY = e.clientY
    d.lastT = e.timeStamp
  }
  function onPointerUp(e: ReactPointerEvent<HTMLDivElement>): void {
    const d = drag.current
    drag.current = null
    const el = panelRef.current
    if (!d || !el) return
    el.style.translate = ""
    const dy = e.clientY - d.y
    const velocity = (e.clientY - d.lastY) / Math.max(1, e.timeStamp - d.lastT) || dy / Math.max(1, e.timeStamp - d.t)
    const decision = sheetRelease({ dy, velocity, height: el.offsetHeight, detent, detents, dismissible })
    if (decision.kind === "dismiss") onDismiss()
    else if (decision.detent !== detent) {
      setDetent(decision.detent)
      if (readPlatform() === "android") haptic("tap")
    }
  }

  return (
    <div
      ref={panelRef}
      data-detent={detent}
      data-closing={closing || undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      style={{ ...style, ["--lm-keyboard-inset" as string]: `${keyboard}px` }}
      className={cn("lm-sheet", className)}
      {...panel}
    >
      <div data-sheet-drag-region className="flex flex-col items-center select-none">
        {dismissible || detents.length > 1 ? <SheetGrabber /> : null}
        {header}
      </div>
      <div data-sheet-body className="min-h-0 flex-1 overflow-y-auto overscroll-contain lm-scroll">
        {children}
      </div>
    </div>
  )
})
