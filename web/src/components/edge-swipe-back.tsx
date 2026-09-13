/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V4 */
import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useDragGesture } from "@/lib/gestures/useDragGesture"
import { EDGE_ZONE_PX, edgeSwipeDecision } from "@/lib/nav/edgeSwipeBack"
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

  useEffect(() => {
    rootRef.current = document.documentElement
  }, [])

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
    startFilter: (event) => {
      if (typeof window === "undefined") return false
      const dir = getComputedStyle(document.documentElement).direction === "rtl" ? -1 : 1
      dirRef.current = dir
      startXRef.current = event.clientX
      // Gate pointer capture to the edge zone itself — anywhere else on the
      // page a drag is scrolling, or one of B4's own gestures, not this one.
      return dir === 1 ? event.clientX <= EDGE_ZONE_PX : event.clientX >= window.innerWidth - EDGE_ZONE_PX
    },
    onCommit: (dx, dy) => {
      const decision = edgeSwipeDecision({
        startX: startXRef.current,
        dx,
        dy,
        viewportWidth: window.innerWidth,
        standalone,
        dir: dirRef.current,
      })
      if (decision !== "back") return
      const target = backTarget(window.history.state?.idx, portalRootFallback(location.pathname))
      if (target.kind === "history") navigate(-1)
      else navigate(target.to, { replace: true, viewTransition: true })
    },
  })

  return null
}
