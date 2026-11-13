/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V4 */
import { useEffect, useLayoutEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useDragGesture } from "@/lib/gestures/useDragGesture"
import { GESTURE_INTERACTIVE_SELECTOR } from "@/lib/gestures/interactiveSelector"
import { swipeBackRelease, swipeSettleMs } from "@/lib/gestures/sheetMath"
import { EDGE_ZONE_PX, edgeSwipeDecision, markSwipeNav } from "@/lib/nav/edgeSwipeBack"
import { backTarget } from "@/lib/nav/backTarget"
import { isStandaloneDisplay } from "@/lib/pwa/useInstallPrompt"
import { PHONE_MEDIA, isNativeFrame } from "@/lib/useNativeFrame"
import { readPlatform } from "@/lib/platform"

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

/** A motion token (`--dur-fast`) in ms; `fallback` when the stylesheet has not defined it. */
function durationToken(name: string, fallback: number): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const ms = raw.endsWith("ms") ? parseFloat(raw) : raw.endsWith("s") ? parseFloat(raw) * 1000 : NaN
  return Number.isFinite(ms) ? ms : fallback
}

/** If the router never reports the navigation, give the column back after this long. */
const COMMIT_GUARD_MS = 1500

export function EdgeSwipeBack() {
  const navigate = useNavigate()
  const location = useLocation()
  const rootRef = useRef<HTMLElement | null>(null)
  const startXRef = useRef(0)
  const dirRef = useRef<1 | -1>(1)
  const columnRef = useRef<HTMLElement | null>(null)
  // True from release until the column is home (cancel) or the new page is in (commit): a
  // second drag cannot start while the first is still travelling.
  const settlingRef = useRef(false)
  // A committed swipe is carrying the column off screen; the next location change ends it.
  const committingRef = useRef(false)
  const guardRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    rootRef.current = document.documentElement
    columnRef.current = document.querySelector<HTMLElement>("[data-shell-column]")
  }, [])

  function clearSwipeState(): void {
    const root = document.documentElement
    root.removeAttribute("data-swiping")
    root.removeAttribute("data-swipe-settling")
    root.style.removeProperty("--lm-swipe-progress")
    root.style.removeProperty("--lm-swipe-dur")
  }

  /** The column and every swipe flag back to rest. */
  function resetColumn(): void {
    if (guardRef.current !== null) {
      clearTimeout(guardRef.current)
      guardRef.current = null
    }
    committingRef.current = false
    settlingRef.current = false
    const column = columnRef.current
    if (column) {
      column.style.transform = ""
      column.style.transition = ""
    }
    clearSwipeState()
  }

  // The new page is in the DOM by now: only here may the column come back, or the old page
  // would flash at x=0 for a frame between the slide off and the navigation.
  useLayoutEffect(() => {
    if (committingRef.current) resetColumn()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key])
  useEffect(() => resetColumn, [])

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
    springEasing: "var(--ease-ios-spring)",
    keepTransformOnCommit: true,
    startFilter: (event) => {
      if (typeof window === "undefined" || settlingRef.current) return false
      columnRef.current = document.querySelector<HTMLElement>("[data-shell-column]")
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
      root.removeAttribute("data-swipe-settling")
      root.setAttribute("data-swiping", "")
      root.style.setProperty("--lm-swipe-progress", String(Math.min(1, Math.max(0, away / width))))
    },
    // Cancel: the hook springs the column home on the iOS curve; the dim and shadow fade over the
    // same duration, and the swipe state clears only once the column is home (`onSettled`).
    onCancel: () => {
      const root = document.documentElement
      if (!root.hasAttribute("data-swiping")) return
      settlingRef.current = true
      root.style.removeProperty("--lm-swipe-dur")
      void root.offsetWidth
      root.setAttribute("data-swipe-settling", "cancel")
      root.style.setProperty("--lm-swipe-progress", "0")
    },
    onSettled: () => {
      if (committingRef.current) return
      settlingRef.current = false
      clearSwipeState()
    },
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
    // Commit: the gesture continues. The column carries on from the release offset to the far
    // edge, at the release speed (clamped to the motion tokens), while the dim and the parallax
    // strip run to rest; only then does the router navigate, with no view transition for this hop
    // (the destination is not a snapshot, and a pop would not run one anyway). Reduced motion
    // skips the slide; the column still holds its offset until the new page is in.
    onCommit: (dx, _dy, velocity) => {
      const dir = dirRef.current
      const width = window.innerWidth
      const root = document.documentElement
      const column = columnRef.current
      const inFrame = isNativeFrame(readPlatform(), window.matchMedia(PHONE_MEDIA).matches)
      const target = backTarget(window.history.state?.idx, portalRootFallback(location.pathname))
      const go = () => {
        markSwipeNav()
        if (target.kind === "history") navigate(-1)
        else navigate(target.to, { replace: true, viewTransition: !inFrame })
      }
      committingRef.current = true
      settlingRef.current = true
      guardRef.current = setTimeout(resetColumn, COMMIT_GUARD_MS)
      if (!inFrame || !column) {
        // No underlay is drawn outside the frame: hand the column back and let the pop transition play.
        column?.style.removeProperty("transform")
        clearSwipeState()
        go()
        return
      }
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      const ms = reduced
        ? 0
        : swipeSettleMs({
            remaining: Math.max(0, width - Math.max(0, dx * dir)),
            velocity: velocity * dir,
            minMs: durationToken("--dur-fast", 150),
            maxMs: durationToken("--dur-base", 200),
          })
      if (ms === 0) {
        go()
        return
      }
      root.style.setProperty("--lm-swipe-dur", `${ms}ms`)
      root.setAttribute("data-swipe-settling", "commit")
      column.style.transition = `transform ${ms}ms var(--ease-ios-spring)`
      void column.offsetWidth
      column.style.transform = `translateX(${dir * 100}%)`
      root.style.setProperty("--lm-swipe-progress", "1")
      setTimeout(go, ms)
    },
  })

  return null
}
