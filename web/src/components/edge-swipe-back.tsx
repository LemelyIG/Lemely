/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V4 */
import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useDragGesture } from "@/lib/gestures/useDragGesture"
import { GESTURE_INTERACTIVE_SELECTOR } from "@/lib/gestures/interactiveSelector"
import { swipeBackRelease } from "@/lib/gestures/sheetMath"
import { EDGE_ZONE_PX, edgeSwipeDecision, markSwipeNav } from "@/lib/nav/edgeSwipeBack"
import { backTarget } from "@/lib/nav/backTarget"
import { isStandaloneDisplay } from "@/lib/pwa/useInstallPrompt"

/*
 * Packet B3 (Task 4) · edge-swipe-back, standalone-only (DESIGN.md §15).
 * Renders nothing — it installs one drag listener on the document root and
 * calls `backTarget` (the same decision `BackControl`, Task 2, uses) on
 * commit. A PWA launched to the home screen has no browser chrome at all, so
 * without this a student who drilled three levels deep has no way back
 * except the in-app `BackControl`/sidebar, which `gesture-standalone-pwa-no-
 * back-replacement` named as the gap.
 */

function portalRootFallback(pathname: string): string {
  const segment = pathname.split("/")[1]
  return segment ? `/${segment}` : "/"
}

export function EdgeSwipeBack() {
  const navigate = useNavigate()
  const location = useLocation()
  const rootRef = useRef<HTMLElement | null>(null)
  const startXRef = useRef(0)
  const dirRef = useRef<1 | -1>(1)
  const columnRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    rootRef.current = document.documentElement
    columnRef.current = document.querySelector<HTMLElement>("[data-shell-column]")
  }, [])

  function clearSwipeState(): void {
    const root = document.documentElement
    root.removeAttribute("data-swiping")
    root.style.removeProperty("--lm-swipe-progress")
  }

  const standalone =
    typeof window === "undefined"
      ? false
      : isStandaloneDisplay(
          window.matchMedia("(display-mode: standalone)"),
          (window.navigator as Navigator & { standalone?: boolean }).standalone,
        )

  useDragGesture(rootRef, {
    axis: "x",
    enabled: standalone,
    transformTarget: columnRef,
    touchAction: "pan-y pinch-zoom",
    startFilter: (event) => {
      if (typeof window === "undefined") return false
      // Issue #246/#247's exact mechanism, found by the opus review of that
      // fix: `rootRef` is `document.documentElement`, so with no exemption
      // here, a tap on ANY interactive control that happens to render inside
      // the leading (or, under `dir="rtl"`, trailing) 24px edge strip — the
      // first `BottomNav` item, a full-bleed row's own link — used to arm
      // this gesture in a standalone PWA, `useDragGesture` captured the
      // pointer on the document root, and the click never reached the
      // control. Checked before the edge-zone math below so it applies
      // regardless of direction.
      const target = event.target
      if (target instanceof Element && target.closest(GESTURE_INTERACTIVE_SELECTOR) !== null) return false
      const dir = getComputedStyle(document.documentElement).direction === "rtl" ? -1 : 1
      dirRef.current = dir
      startXRef.current = event.clientX
      // Gate pointer capture to the edge zone itself — anywhere else on the
      // page a drag is scrolling, or one of B4's own gestures, not this one.
      return dir === 1 ? event.clientX <= EDGE_ZONE_PX : event.clientX >= window.innerWidth - EDGE_ZONE_PX
    },
    onProgress: (dx) => {
      const away = dx * dirRef.current
      const width = window.innerWidth
      const root = document.documentElement
      root.setAttribute("data-swiping", "")
      root.style.setProperty("--lm-swipe-progress", String(Math.min(1, Math.max(0, away / width))))
    },
    onCancel: clearSwipeState,
    // Commit versus cancel is the hook's call: a short slow drag cancels and the hook springs
    // the column home; 35% of the width or a fling commits (Task 6 `swipeBackRelease`).
    release: ({ dx, dy, velocity }) => {
      const dir = dirRef.current
      const edge = edgeSwipeDecision({
        startX: startXRef.current,
        dx,
        dy,
        viewportWidth: window.innerWidth,
        standalone,
        dir,
      })
      return edge === "back" ? swipeBackRelease({ dx: dx * dir, velocity: velocity * dir, width: window.innerWidth }) : "cancel"
    },
    onCommit: () => {
      clearSwipeState()
      markSwipeNav()
      const target = backTarget(window.history.state?.idx, portalRootFallback(location.pathname))
      if (target.kind === "history") navigate(-1)
      else navigate(target.to, { replace: true, viewTransition: true })
    },
  })

  return null
}
